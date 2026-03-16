# display/views.py
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
import random
import os
import json
import base64
import logging
import requests
from django.core.files.base import ContentFile
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.conf import settings

# Import models
from .models import (
    Consumer, UserSession, AuditLog, Notification,
    ElectricityConsumer, ElectricityBill, ElectricityPayment, ElectricityComplaint,
    LoadEnhancementRequest, MeterReplacementRequest, NameTransferRequest,
    GasConsumer, GasCylinderBooking, GasComplaint, GasSubsidy,
    WaterConsumer, WaterBill,
    Property, PropertyTax, ProfessionalTax, TradeLicense,
    BuildingPlanApplication, Grievance,
    BirthCertificateApplication, DeathCertificateApplication,
    MarriageRegistration, DocumentUpload
)

# Import security modules
from .decorators import kiosk_login_required, rate_limit, log_activity
from .utils.security import (
    generate_secure_otp, hash_otp, verify_otp_hash, 
    rate_limit_check, validate_aadhaar, sanitize_input,
    mask_sensitive_data, log_security_event, get_client_ip,
    validate_file_extension, validate_file_size
)

logger = logging.getLogger(__name__)


# ================= OTP UTILITY FUNCTIONS =================

def generate_otp(length=6):
    """Generate a cryptographically secure OTP"""
    return generate_secure_otp(length)


def send_otp_via_circuitdigest(phone_number, otp, aadhaar_number):
    """
    Send OTP via CircuitDigest Cloud SMS API (100% free for India)
    Uses Template ID: 101 - "Your {#var1#} is currently at {#var2#}."
    """
    if not phone_number:
        logger.warning(f"No phone number found for Aadhaar {aadhaar_number[-4:]}")
        return False, "No phone number registered"
    
    # Clean phone number - must be 10 digits
    digits_only = ''.join(filter(str.isdigit, phone_number))
    
    # Format as 91XXXXXXXXXX for API
    if len(digits_only) == 10:
        formatted_phone = '91' + digits_only
    elif len(digits_only) == 12 and digits_only.startswith('91'):
        formatted_phone = digits_only
    else:
        logger.error(f"Invalid phone number format: {phone_number}")
        return False, "Invalid phone number format"
    
    # Get API key from settings
    api_key = settings.CIRCUITDIGEST_API_KEY
    template_id = getattr(settings, 'CIRCUITDIGEST_TEMPLATE_ID', '101')
    console_logging = getattr(settings, 'OTP_CONSOLE_LOGGING', True)
    
    if not api_key:
        logger.error("CircuitDigest API key not configured")
        return False, "SMS service not configured"
    
    try:
        # For development/testing - log to console
        if console_logging:
            log_message = f"""
            ===== OTP for Aadhaar {aadhaar_number[-4:]} =====
            Phone: {formatted_phone}
            OTP: {otp}
            Template ID: {template_id}
            ============================================
            """
            print(log_message)
            logger.info(f"OTP sent via console to {formatted_phone[-4:]}")
            return True, "OTP logged to console"
        
        # Prepare API request
        url = "https://www.circuitdigest.cloud/api/v1/send_sms"
        
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }
        
        # Payload - Template 101 expects var1 and var2
        payload = {
            "mobiles": formatted_phone,
            "var1": "OTP",
            "var2": otp
        }
        
        # Add template ID as query parameter
        full_url = f"{url}?ID={template_id}"
        
        print(f"\n📤 Sending OTP via CircuitDigest...")
        print(f"Phone: {formatted_phone}")
        print(f"OTP: {otp}")
        
        # Send request with timeout
        response = requests.post(
            full_url, 
            headers=headers, 
            json=payload, 
            timeout=15
        )
        
        print(f"📥 Response Status: {response.status_code}")
        print(f"📥 Response Body: {response.text}")
        
        # Check response
        if response.status_code == 200:
            try:
                result = response.json()
                if result.get('status') == 'success' or 'success' in str(result).lower():
                    logger.info(f"✅ OTP sent via CircuitDigest to {formatted_phone[-4:]}")
                    return True, "OTP sent successfully"
                else:
                    error_msg = result.get('message', 'Unknown error')
                    logger.error(f"CircuitDigest API error: {error_msg}")
                    return False, f"Failed to send OTP: {error_msg}"
            except:
                # If response is not JSON but 200, assume success
                logger.info(f"✅ OTP sent (non-JSON response)")
                return True, "OTP sent successfully"
        else:
            logger.error(f"CircuitDigest HTTP error: {response.status_code}")
            return False, f"Failed to send OTP: HTTP {response.status_code}"
            
    except requests.exceptions.Timeout:
        logger.error(f"Timeout error")
        return False, "Failed to send OTP: Request timeout"
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error")
        return False, "Failed to send OTP: Network connection error"
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return False, f"Failed to send OTP: {str(e)}"


def verify_otp(stored_hash, entered_otp, otp_timestamp):
    """
    Verify OTP using hash comparison and check expiry (5 minutes)
    """
    if not stored_hash or not entered_otp:
        return False, "OTP missing"
    
    # Verify using hash
    if not verify_otp_hash(stored_hash, entered_otp):
        return False, "Invalid OTP"
    
    # Check if OTP is expired (5 minutes)
    expiry_time = otp_timestamp + timedelta(minutes=5)
    if datetime.now() > expiry_time:
        return False, "OTP expired"
    
    return True, "OTP verified"


# ================= CORE / AUTH =================

def index(request):
    return render(request, 'index.html')


@rate_limit(max_attempts=3, time_window=300, key_prefix='auth')
def auth(request):
    """Aadhaar authentication page with enhanced security"""
    # Clear any existing messages
    storage = messages.get_messages(request)
    storage.used = True
    
    # CRITICAL: If there's ANY query parameter, redirect to clean URL
    if request.GET:
        return redirect('auth')
    
    if request.method == 'POST':
        aadhaar_number = sanitize_input(request.POST.get('aadhaar_number'), 12)
        
        # Validate Aadhaar with Verhoeff algorithm
        is_valid, message = validate_aadhaar(aadhaar_number)
        if not is_valid:
            messages.error(request, message)
            log_security_event(request, 'INVALID_AADHAAR', {'reason': message})
            return render(request, 'auth.html')
        
        try:
            # Check if consumer exists in database
            consumer = Consumer.objects.get(aadhaar_number=aadhaar_number, is_active=True)
            
            # Store in session
            request.session['aadhaar_number'] = aadhaar_number
            request.session['consumer_id'] = consumer.id
            
            # Generate and hash OTP
            otp = generate_secure_otp(6)
            otp_hash = hash_otp(otp)
            
            # Store hash instead of plain OTP
            request.session['otp_hash'] = otp_hash
            request.session['otp_attempts'] = 0
            request.session['otp_timestamp'] = datetime.now().isoformat()
            
            # Send OTP via CircuitDigest
            print(f"\n🔐 Generated OTP for {consumer.name}: {otp}")
            print(f"📱 Sending to: {consumer.mobile}")
            
            success, message = send_otp_via_circuitdigest(
                consumer.mobile,
                otp,
                aadhaar_number
            )
            
            if success:
                messages.success(request, 'OTP sent successfully to your registered mobile number')
                
                # Create audit log
                AuditLog.objects.create(
                    consumer=consumer,
                    action='OTP_SENT',
                    model_name='Consumer',
                    object_id=consumer.id,
                    changes={'aadhaar': aadhaar_number[-4:]},
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
                
                return redirect('otp')
            else:
                messages.error(request, f'Failed to send OTP: {message}')
                # Fallback - show OTP in console for testing
                messages.info(request, f'OTP for testing: {otp} (Check console)')
                print(f"\n⚠️ FALLBACK OTP: {otp}")
                return redirect('otp')
                
        except Consumer.DoesNotExist:
            messages.error(request, 'Aadhaar number not found in our records. Please contact support.')
            
            # Log failed attempt
            AuditLog.objects.create(
                consumer=None,
                action='AUTH_FAILED',
                model_name='Consumer',
                object_id='',
                changes={'aadhaar': aadhaar_number[-4:]},
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
            
            return render(request, 'auth.html')
        except Exception as e:
            logger.error(f"Error during authentication: {str(e)}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'auth.html')
    
    # GET request - show the Aadhaar entry page
    return render(request, 'auth.html')


@rate_limit(max_attempts=5, time_window=300, key_prefix='otp_verification')
def otp(request):
    """OTP verification page"""
    # Check if aadhaar is in session
    aadhaar_number = request.session.get('aadhaar_number')
    consumer_id = request.session.get('consumer_id')
    stored_otp_hash = request.session.get('otp_hash')
    otp_timestamp_str = request.session.get('otp_timestamp')
    
    if not aadhaar_number or not consumer_id or not stored_otp_hash:
        messages.error(request, 'Session expired. Please enter Aadhaar again.')
        return redirect('auth')
    
    # Parse timestamp
    try:
        otp_timestamp = datetime.fromisoformat(otp_timestamp_str)
    except:
        otp_timestamp = datetime.now() - timedelta(minutes=6)  # Force expiry
    
    if request.method == 'POST':
        entered_otp = sanitize_input(request.POST.get('otp'), 6)
        
        # Get attempt count
        attempts = request.session.get('otp_attempts', 0)
        request.session['otp_attempts'] = attempts + 1
        
        if attempts >= 3:
            messages.error(request, 'Too many failed attempts. Please request new OTP.')
            log_security_event(request, 'OTP_ATTEMPTS_EXCEEDED', {'aadhaar': aadhaar_number[-4:]})
            return redirect('resend-otp')
        
        # Verify OTP using hash
        is_valid, message = verify_otp(stored_otp_hash, entered_otp, otp_timestamp)
        
        if is_valid:
            # OTP verified successfully
            request.session['aadhaar_verified'] = True
            request.session['otp_verified'] = True
            
            # Generate CSRF token for session
            from .utils.security import generate_csrf_token
            request.session['csrf_token'] = generate_csrf_token()
            
            # Update consumer last login
            try:
                consumer = Consumer.objects.get(id=consumer_id)
                consumer.last_login = datetime.now()
                consumer.save()
                
                # Handle UserSession creation properly
                session_key = request.session.session_key
                
                # Deactivate any existing active sessions for this consumer
                UserSession.objects.filter(
                    consumer=consumer,
                    is_active=True
                ).update(is_active=False)
                
                # Check if this session key already exists
                existing_session = UserSession.objects.filter(
                    session_key=session_key
                ).first()
                
                if existing_session:
                    # Update existing session
                    existing_session.consumer = consumer
                    existing_session.ip_address = get_client_ip(request)
                    existing_session.user_agent = request.META.get('HTTP_USER_AGENT', '')
                    existing_session.is_active = True
                    existing_session.save()
                    logger.info(f"✅ Updated existing session: {session_key}")
                else:
                    # Create new session
                    UserSession.objects.create(
                        consumer=consumer,
                        session_key=session_key,
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')
                    )
                    logger.info(f"✅ Created new session: {session_key}")
                
                # Create notification
                Notification.objects.create(
                    consumer=consumer,
                    notification_type='GENERAL',
                    title='Login Successful',
                    message=f'You have successfully logged in to Civic Kiosk at {datetime.now().strftime("%d %b %Y %I:%M %p")}'
                )
                
                # Clear OTP from session
                request.session.pop('otp_hash', None)
                request.session.pop('otp_timestamp', None)
                
                messages.success(request, 'OTP verified successfully!')
                
            except Consumer.DoesNotExist:
                messages.error(request, 'Consumer record not found.')
                return redirect('auth')
            
            return redirect('menu')
        else:
            messages.error(request, message)
            log_security_event(request, 'OTP_INVALID', {'aadhaar': aadhaar_number[-4:]})
    
    # Mask Aadhaar for display
    masked_aadhaar = 'XXXX XXXX ' + aadhaar_number[-4:]
    
    # Get consumer details for display
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        consumer_name = consumer.name
        consumer_phone = consumer.mobile
        # Mask phone number for display (show only last 4 digits)
        masked_phone = consumer_phone[-4:] if consumer_phone else ''
    except:
        consumer_name = ''
        masked_phone = ''
    
    context = {
        'aadhaar': masked_aadhaar,
        'consumer_name': consumer_name,
        'masked_phone': masked_phone,
        'attempts': request.session.get('otp_attempts', 0)
    }
    
    return render(request, 'otp.html', context)


@rate_limit(max_attempts=3, time_window=600, key_prefix='resend_otp')
def resend_otp(request):
    """Resend OTP with rate limiting"""
    if request.method == 'POST':
        aadhaar_number = request.session.get('aadhaar_number')
        consumer_id = request.session.get('consumer_id')
        
        if not aadhaar_number or not consumer_id:
            messages.error(request, 'Session expired. Please login again.')
            return redirect('auth')
        
        try:
            consumer = Consumer.objects.get(id=consumer_id, aadhaar_number=aadhaar_number)
            
            # Generate new OTP
            otp = generate_secure_otp(6)
            otp_hash = hash_otp(otp)
            request.session['otp_hash'] = otp_hash
            request.session['otp_attempts'] = 0
            request.session['otp_timestamp'] = datetime.now().isoformat()
            
            # Send OTP via CircuitDigest
            success, message = send_otp_via_circuitdigest(consumer.mobile, otp, aadhaar_number)
            
            if success:
                messages.success(request, 'New OTP sent successfully to your registered mobile number')
                
                # Create audit log
                AuditLog.objects.create(
                    consumer=consumer,
                    action='OTP_RESENT',
                    model_name='Consumer',
                    object_id=consumer.id,
                    changes={'aadhaar': aadhaar_number[-4:]},
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
            else:
                messages.error(request, f'Failed to send OTP: {message}')
                # Fallback
                messages.info(request, f'New OTP: {otp}')
                print(f"\n⚠️ FALLBACK RESEND OTP: {otp}")
                
        except Consumer.DoesNotExist:
            messages.error(request, 'Consumer record not found.')
            return redirect('auth')
        except Exception as e:
            logger.error(f"Error resending OTP: {str(e)}")
            messages.error(request, 'An error occurred. Please try again.')
    
    return redirect('otp')


@log_activity('LOGOUT')
def logout(request):
    """Logout user - properly clean up session"""
    consumer_id = request.session.get('consumer_id')
    session_key = request.session.session_key
    
    if consumer_id and session_key:
        try:
            # Mark this specific session as inactive
            UserSession.objects.filter(
                consumer_id=consumer_id,
                session_key=session_key
            ).update(is_active=False)
            logger.info(f"✅ Session {session_key} deactivated for consumer {consumer_id}")
        except Exception as e:
            logger.error(f"Error deactivating session: {e}")
    
    # Clear session
    request.session.flush()
    messages.success(request, 'You have been logged out successfully.')
    return redirect('index')


@kiosk_login_required
@log_activity('VIEW_MENU')
def menu(request):
    """Main menu after authentication"""
    # Get consumer info for display
    consumer_id = request.session.get('consumer_id')
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        context = {
            'consumer_name': consumer.name,
            'consumer_aadhaar': consumer.aadhaar_number[-4:],
            'consumer_phone': consumer.mobile[-4:],
            'notifications': Notification.objects.filter(consumer=consumer, is_read=False).count()
        }
    except:
        context = {}
    
    return render(request, 'menu.html', context)


# ================= ELECTRICITY =================

@kiosk_login_required
def electricity_services(request):
    context = {
        'page_title': 'Electricity Services',
        'current_date': datetime.now().strftime('%d %b %Y'),
    }
    return render(request, 'electricity-services.html', context)


@kiosk_login_required
@rate_limit(max_attempts=10, time_window=300, key_prefix='bill_payment')
def electricity_bill_payment(request):
    context = {}
    
    if request.method == 'POST':
        action = sanitize_input(request.POST.get('action'))
        consumer_number = sanitize_input(request.POST.get('consumer_number'), 20)
        bill_amount = sanitize_input(request.POST.get('bill_amount'))
        
        # FIELDS for payment method
        payment_method = sanitize_input(request.POST.get('payment_method'))
        upi_id = sanitize_input(request.POST.get('upi_id'), 50)
        card_number = sanitize_input(request.POST.get('card_number'), 19)
        cvv = sanitize_input(request.POST.get('cvv'), 3)
        pin = sanitize_input(request.POST.get('pin'), 4)
        
        if action == 'pay':
            if not consumer_number or not bill_amount:
                messages.error(request, 'Invalid bill details')
                return render(request, 'electricity-bill-payment.html', context)
            
            # Validate based on payment method
            if payment_method == 'upi':
                if not upi_id:
                    messages.error(request, 'Please provide UPI ID for payment')
                    return render(request, 'electricity-bill-payment.html', context)
                payment_details = f"UPI ID: {upi_id}"
            elif payment_method == 'atm':
                if not card_number or not cvv or not pin:
                    messages.error(request, 'Please provide complete card details')
                    return render(request, 'electricity-bill-payment.html', context)
                
                # Validate card number (basic check)
                card_clean = card_number.replace(' ', '')
                if len(card_clean) < 15 or not card_clean.isdigit():
                    messages.error(request, 'Please enter a valid card number')
                    return render(request, 'electricity-bill-payment.html', context)
                
                # Validate CVV
                if len(cvv) != 3 or not cvv.isdigit():
                    messages.error(request, 'Please enter a valid 3-digit CVV')
                    return render(request, 'electricity-bill-payment.html', context)
                
                # Validate PIN
                if len(pin) != 4 or not pin.isdigit():
                    messages.error(request, 'Please enter a valid 4-digit PIN')
                    return render(request, 'electricity-bill-payment.html', context)
                    
                # Mask card number for display
                masked_card = 'XXXX XXXX XXXX ' + card_clean[-4:]
                payment_details = f"Card: {masked_card}"
            else:
                messages.error(request, 'Please select a payment method')
                return render(request, 'electricity-bill-payment.html', context)
            
            # Generate transaction ID
            transaction_id = f"TXN{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
            
            # Log payment
            log_security_event(request, 'PAYMENT_INITIATED', {
                'service': 'electricity',
                'amount': bill_amount,
                'method': payment_method
            })
            
            messages.success(request, f'Payment of ₹{bill_amount} for consumer {consumer_number} successful! Transaction ID: {transaction_id}')
            return redirect('payment-history')
        
        elif action == 'fetch':
            context['show_bill'] = True
            context['consumer_number'] = consumer_number
    
    return render(request, 'electricity-bill-payment.html', context)


@kiosk_login_required
def electricity_duplicate_bill(request):
    context = {}
    
    if request.method == 'POST':
        action = sanitize_input(request.POST.get('action'))
        
        if action == 'download':
            bill_id = sanitize_input(request.POST.get('bill_id'), 50)
            bill_month = sanitize_input(request.POST.get('bill_month'), 20)
            
            if bill_id and bill_month:
                messages.success(request, f'Bill for {bill_month} downloaded successfully!')
            
            return redirect('electricity-duplicate-bill')
        
        elif action == 'pay':
            # Redirect to payment page with bill details
            bill_month = sanitize_input(request.POST.get('bill_month'), 20)
            bill_amount = sanitize_input(request.POST.get('bill_amount'))
            bill_number = sanitize_input(request.POST.get('bill_number'), 50)
            
            # Store in session for payment page
            request.session['pending_payment'] = {
                'service': 'electricity',
                'consumer_no': sanitize_input(request.POST.get('consumer_number'), 20),
                'amount': bill_amount,
                'bill_number': bill_number,
                'bill_month': bill_month
            }
            
            return redirect('electricity-bill-payment')
        
        else:  # Search action
            consumer_number = sanitize_input(request.POST.get('consumer_number'), 20)
            
            if not consumer_number or len(consumer_number) < 6:
                messages.error(request, 'Please enter a valid consumer number')
                return render(request, 'electricity-duplicate-bill.html', context)
            
            today = datetime.now().date()
            bills = []
            
            for i in range(3):
                bill_date = today - relativedelta(months=i)
                due_date = bill_date + relativedelta(days=15)
                
                bills.append({
                    'id': f'bill_{i+1}',
                    'month': bill_date.strftime('%B'),
                    'year': bill_date.year,
                    'bill_date': bill_date.strftime('%d %b %Y'),
                    'due_date': due_date.strftime('%d %b %Y'),
                    'amount': f"{1200 + (i * 70)}",
                    'bill_number': f"EB/{bill_date.year}/{random.randint(1000, 9999)}",
                    'units': 200 + (i * 25)
                })
            
            context['bills'] = bills
            context['show_bills'] = True
            context['consumer_number'] = consumer_number
    
    return render(request, 'electricity-duplicate-bill.html', context)


@kiosk_login_required
def electricity_solar(request):
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number'), 20)
        solar_capacity = sanitize_input(request.POST.get('solar_capacity'))
        roof_area = sanitize_input(request.POST.get('roof_area'))
        
        if not consumer_number or not solar_capacity:
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'electricity-solar.html')
        
        ref_number = f"SOLAR{random.randint(100000, 999999)}"
        messages.success(request, f'Solar net metering application submitted! Reference: {ref_number}')
        return redirect('electricity-services')
    
    return render(request, 'electricity-solar.html')


@kiosk_login_required
def electricity_new_connection(request):
    if request.method == 'POST':
        full_name = sanitize_input(request.POST.get('full_name'), 100)
        address = sanitize_input(request.POST.get('address'), 500)
        property_type = sanitize_input(request.POST.get('property_type'), 20)
        load_required = sanitize_input(request.POST.get('load_required'))
        mobile_number = sanitize_input(request.POST.get('mobile_number'), 10)
        
        if not full_name:
            messages.error(request, 'Please enter your full name')
            return render(request, 'electricity-new-connection.html')
        
        if not address:
            messages.error(request, 'Please enter your address')
            return render(request, 'electricity-new-connection.html')
        
        if not load_required:
            messages.error(request, 'Please enter load required')
            return render(request, 'electricity-new-connection.html')
        
        try:
            load_value = float(load_required)
            if load_value <= 0:
                messages.error(request, 'Load required must be a positive number')
                return render(request, 'electricity-new-connection.html')
            if load_value > 100:
                messages.error(request, 'Maximum load allowed is 100 kW. Please contact commercial office for higher loads.')
                return render(request, 'electricity-new-connection.html')
        except ValueError:
            messages.error(request, 'Please enter a valid load value')
            return render(request, 'electricity-new-connection.html')
        
        if not mobile_number or not mobile_number.isdigit() or len(mobile_number) != 10:
            messages.error(request, 'Please enter a valid 10-digit mobile number')
            return render(request, 'electricity-new-connection.html')
        
        ref_number = f"ELEC{random.randint(100000, 999999)}"
        messages.success(request, f'New connection application submitted successfully! Reference: {ref_number}')
        return redirect('electricity-services')
    
    return render(request, 'electricity-new-connection.html')


@kiosk_login_required
def electricity_name_transfer(request):
    context = {}
    
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number', '123456789012'), 20)
        new_owner_name = sanitize_input(request.POST.get('new_owner_name'), 100)
        new_owner_aadhaar = sanitize_input(request.POST.get('new_owner_aadhaar'), 12)
        relationship = sanitize_input(request.POST.get('relationship'), 50)
        
        # NEW FIELDS
        new_owner_phone = sanitize_input(request.POST.get('new_owner_phone'), 10)
        new_owner_email = sanitize_input(request.POST.get('new_owner_email'), 100)
        transfer_fee = sanitize_input(request.POST.get('transfer_fee', 500))
        
        # File uploads
        sale_deed = request.FILES.get('sale_deed')
        noc = request.FILES.get('noc')
        id_proof = request.FILES.get('id_proof')
        address_proof = request.FILES.get('address_proof')
        
        if not new_owner_name:
            messages.error(request, 'Please enter new owner name')
            return render(request, 'electricity-name-transfer.html', context)
        
        if not new_owner_aadhaar:
            messages.error(request, 'Please enter new owner Aadhaar number')
            return render(request, 'electricity-name-transfer.html', context)
        
        # Validate Aadhaar
        is_valid, message = validate_aadhaar(new_owner_aadhaar)
        if not is_valid:
            messages.error(request, message)
            return render(request, 'electricity-name-transfer.html', context)
        
        # Validate phone if provided
        if new_owner_phone and (not new_owner_phone.isdigit() or len(new_owner_phone) != 10):
            messages.error(request, 'Please enter a valid 10-digit mobile number')
            return render(request, 'electricity-name-transfer.html', context)
        
        # Validate email if provided
        if new_owner_email:
            try:
                validate_email(new_owner_email)
            except ValidationError:
                messages.error(request, 'Please enter a valid email address')
                return render(request, 'electricity-name-transfer.html', context)
        
        # Validate required documents
        required_docs = [sale_deed, noc, id_proof, address_proof]
        doc_names = ['Sale Deed', 'NOC', 'ID Proof', 'Address Proof']
        missing_docs = []
        
        for i, doc in enumerate(required_docs):
            if not doc:
                missing_docs.append(doc_names[i])
            else:
                # Validate file extension
                is_valid_ext, ext = validate_file_extension(doc.name, ['.pdf', '.jpg', '.jpeg', '.png'])
                if not is_valid_ext:
                    messages.error(request, f'{doc_names[i]}: Invalid file type. Only PDF, JPG, PNG allowed.')
                    return render(request, 'electricity-name-transfer.html', context)
                
                # Validate file size
                is_valid_size, size = validate_file_size(doc, 25)
                if not is_valid_size:
                    messages.error(request, f'{doc_names[i]}: File size exceeds 25MB limit.')
                    return render(request, 'electricity-name-transfer.html', context)
        
        if missing_docs:
            messages.error(request, f'Please upload all required documents. Missing: {", ".join(missing_docs)}')
            return render(request, 'electricity-name-transfer.html', context)
        
        ref_number = f"TRAN{random.randint(100000, 999999)}"
        messages.success(request, f'Name transfer request submitted successfully! Reference: {ref_number}')
        return redirect('electricity-services')
    
    context['current_owner'] = 'Rajesh Kumar'
    context['consumer_number'] = '123456789012'
    context['address'] = '123, Gandhi Nagar'
    context['transfer_fee'] = 500
    context['document_fee'] = 200
    context['total_fee'] = 826  # 500 + 200 + 18% GST
    
    return render(request, 'electricity-name-transfer.html', context)


@kiosk_login_required
def electricity_meter_replacement(request):
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number', '123456789012'), 20)
        meter_type = sanitize_input(request.POST.get('meter_type'), 20)
        meter_price = sanitize_input(request.POST.get('meter_price'))
        reason = sanitize_input(request.POST.get('reason'), 50)
        preferred_date = sanitize_input(request.POST.get('preferred_date'), 10)
        
        # NEW FIELDS
        preferred_time = sanitize_input(request.POST.get('preferred_time', '09:00-12:00'), 20)
        additional_services = sanitize_input(request.POST.get('additional_services', ''))
        
        if not all([meter_type, reason, preferred_date]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'electricity-meter-replacement.html')
        
        from datetime import date
        try:
            pref_date = date.fromisoformat(preferred_date)
            if pref_date < date.today():
                messages.error(request, 'Preferred date cannot be in the past')
                return render(request, 'electricity-meter-replacement.html')
        except ValueError:
            messages.error(request, 'Invalid date format')
            return render(request, 'electricity-meter-replacement.html')
        
        # Calculate total with additional services
        try:
            meter_price_float = float(meter_price) if meter_price else 1200
        except ValueError:
            meter_price_float = 1200
            
        installation_fee = 500
        additional_cost = 0
        additional_services_list = additional_services.split(',') if additional_services else []
        
        if 'calibration' in additional_services_list:
            additional_cost += 300
        if 'wiring' in additional_services_list:
            additional_cost += 500
        if 'seal' in additional_services_list:
            additional_cost += 100
        
        subtotal = meter_price_float + installation_fee + additional_cost
        total_with_gst = subtotal * 1.18
        
        ref_number = f"METER{random.randint(100000, 999999)}"
        messages.success(request, f'Meter replacement request submitted successfully! Reference: {ref_number}')
        return redirect('electricity-services')
    
    return render(request, 'electricity-meter-replacement.html')


@kiosk_login_required
def electricity_load_enhancement(request):
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number', '123456789012'), 20)
        current_load = sanitize_input(request.POST.get('current_load', '3'))
        requested_load = sanitize_input(request.POST.get('requested_load'))
        reason = sanitize_input(request.POST.get('reason'), 50)
        
        # NEW FIELD
        reason_details = sanitize_input(request.POST.get('reason_details', ''), 500)
        
        if not requested_load:
            messages.error(request, 'Please enter requested load')
            return render(request, 'electricity-load-enhancement.html')
        
        try:
            requested_load_float = float(requested_load)
            current_load_float = float(current_load)
            
            if requested_load_float <= current_load_float:
                messages.error(request, f'Requested load must be greater than current load ({current_load} kW)')
                return render(request, 'electricity-load-enhancement.html')
            
            if requested_load_float > 50:
                messages.error(request, 'Maximum load enhancement is 50 kW. Please contact commercial office for higher loads.')
                return render(request, 'electricity-load-enhancement.html')
                
        except ValueError:
            messages.error(request, 'Please enter a valid load value')
            return render(request, 'electricity-load-enhancement.html')
        
        # Validate reason details for 'Other' or 'EV Charger'
        if reason in ['Other', 'EV Charger'] and not reason_details:
            messages.error(request, f'Please provide details for {reason} reason')
            return render(request, 'electricity-load-enhancement.html')
        
        ref_number = f"LOAD{random.randint(100000, 999999)}"
        messages.success(request, f'Load enhancement request submitted successfully! Reference: {ref_number}')
        return redirect('electricity-services')
    
    return render(request, 'electricity-load-enhancement.html')


@kiosk_login_required
def electricity_complaint(request):
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number', '123456789012'), 20)
        complaint_type = sanitize_input(request.POST.get('complaint_type'), 50)
        complaint_description = sanitize_input(request.POST.get('complaint_description'), 1000)
        
        # NEW FIELDS
        complaint_priority = sanitize_input(request.POST.get('complaint_priority', 'Normal'), 20)
        contact_phone = sanitize_input(request.POST.get('contact_phone'), 10)
        
        if not all([complaint_type, complaint_description]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'electricity-complaint.html')
        
        consumer_number_clean = consumer_number.replace(' ', '')
        if len(consumer_number_clean) < 6 or not consumer_number_clean.isdigit():
            messages.error(request, 'Please enter a valid consumer number')
            return render(request, 'electricity-complaint.html')
        
        # Validate phone if provided
        if contact_phone and (not contact_phone.isdigit() or len(contact_phone) != 10):
            messages.error(request, 'Please enter a valid 10-digit mobile number')
            return render(request, 'electricity-complaint.html')
        
        # Priority-based response message
        response_times = {
            'Normal': '24 hours',
            'Urgent': '4 hours',
            'Emergency': '30 minutes'
        }
        response_time = response_times.get(complaint_priority, '24 hours')
        
        ref_number = f"ELC{random.randint(100000, 999999)}"
        messages.success(request, f'Complaint registered successfully! Reference: {ref_number}. Expected response time: {response_time}')
        return redirect('electricity-services')
    
    return render(request, 'electricity-complaint.html')


# ================= WATER =================

@kiosk_login_required
def water_bill(request):
    if request.method == 'POST':
        action = sanitize_input(request.POST.get('action'))
        consumer_no = sanitize_input(request.POST.get('consumer_no'), 20)
        
        if action == 'pay':
            bill_amount = sanitize_input(request.POST.get('bill_amount'))
            payment_method = sanitize_input(request.POST.get('payment_method', 'upi'), 10)
            
            if not consumer_no or not bill_amount:
                messages.error(request, 'Invalid bill details')
                return render(request, 'water-bill.html')
            
            # Generate transaction ID
            transaction_id = f"WTR{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
            
            messages.success(request, f'Water bill payment of ₹{bill_amount} for consumer {consumer_no} successful! Transaction ID: {transaction_id}')
            return redirect('municipal-services')
        
        elif action == 'fetch':
            if not consumer_no:
                messages.error(request, 'Please enter consumer number')
                return render(request, 'water-bill.html')
            
            context = {
                'show_bill': True,
                'consumer_no': consumer_no,
                'consumer_name': 'Rajesh Kumar',
                'bill_number': f'WATER/{datetime.now().year}/{random.randint(1000, 9999)}',
                'bill_date': datetime.now().strftime('%d %b %Y'),
                'due_date': (datetime.now() + timedelta(days=15)).strftime('%d %b %Y'),
                'units_consumed': random.randint(20, 30),
                'bill_amount': random.randint(400, 600)
            }
            return render(request, 'water-bill.html', context)
    
    return render(request, 'water-bill.html')


# ================= MUNICIPAL SERVICES =================

@kiosk_login_required
def municipal_services(request):
    return render(request, 'municipal-services.html')


@kiosk_login_required
def trade_license(request):
    if request.method == 'POST':
        business_name = sanitize_input(request.POST.get('business_name'), 100)
        business_type = sanitize_input(request.POST.get('business_type'), 50)
        owner_name = sanitize_input(request.POST.get('owner_name'), 100)
        address = sanitize_input(request.POST.get('address'), 500)
        gst_number = sanitize_input(request.POST.get('gst_number'), 15)
        
        if not all([business_name, business_type, owner_name, address]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'trade-license.html')
        
        # Optional GST validation
        if gst_number and len(gst_number) != 15:
            messages.warning(request, 'GST number should be 15 characters if provided')
        
        ref_number = f"TL{random.randint(100000, 999999)}"
        messages.success(request, f'Trade license application submitted! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'trade-license.html')


@kiosk_login_required
def property_tax(request):
    if request.method == 'POST':
        action = sanitize_input(request.POST.get('action'))
        property_id = sanitize_input(request.POST.get('property_id'), 20)
        
        if action == 'pay':
            tax_amount = sanitize_input(request.POST.get('tax_amount'))
            payment_method = sanitize_input(request.POST.get('payment_method', 'upi'), 10)
            
            if not property_id or not tax_amount:
                messages.error(request, 'Invalid tax details')
                return render(request, 'property-tax.html')
            
            # Generate transaction ID
            transaction_id = f"PTX{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
            
            messages.success(request, f'Property tax of ₹{tax_amount} for property {property_id} paid successfully! Transaction ID: {transaction_id}')
            return redirect('municipal-services')
        
        elif action == 'fetch':
            if not property_id:
                messages.error(request, 'Please enter property ID')
                return render(request, 'property-tax.html')
            
            context = {
                'show_tax': True,
                'property_id': property_id,
                'owner_name': 'Rajesh Kumar',
                'property_type': 'Residential',
                'area': '1,200',
                'assessment_year': '2025-26',
                'due_date': '31 Mar 2026',
                'amount': '3,450.00'
            }
            return render(request, 'property-tax.html', context)
    
    return render(request, 'property-tax.html')


@kiosk_login_required
def professional_tax(request):
    if request.method == 'POST':
        action = sanitize_input(request.POST.get('action'))
        ptin = sanitize_input(request.POST.get('ptin'), 20)
        
        if action == 'pay':
            tax_amount = sanitize_input(request.POST.get('tax_amount'))
            payment_method = sanitize_input(request.POST.get('payment_method', 'upi'), 10)
            
            if not ptin or not tax_amount:
                messages.error(request, 'Invalid tax details')
                return render(request, 'professional-tax.html')
            
            # Generate transaction ID
            transaction_id = f"PRF{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
            
            messages.success(request, f'Professional tax of ₹{tax_amount} for PTIN {ptin} paid successfully! Transaction ID: {transaction_id}')
            return redirect('municipal-services')
        
        elif action == 'fetch':
            if not ptin:
                messages.error(request, 'Please enter PTIN')
                return render(request, 'professional-tax.html')
            
            context = {
                'show_tax': True,
                'ptin': ptin,
                'name': 'Rajesh Kumar',
                'profession': 'Self Employed',
                'assessment_year': '2025-26',
                'due_date': '31 Mar 2026',
                'half_yearly_tax': '1,250',
                'penalty': '0',
                'amount': '1,250.00'
            }
            return render(request, 'professional-tax.html', context)
    
    return render(request, 'professional-tax.html')


@kiosk_login_required
def application_status(request):
    # Sample data - in production, fetch from database
    context = {
        'application': {
            'application_id': 'APP123456',
            'department': 'Electricity',
            'submitted_date': datetime.now().date() - timedelta(days=5),
            'current_stage': 'Document Verification',
            'assigned_officer': 'Mr. Sharma',
            'expected_completion': datetime.now().date() + timedelta(days=10)
        },
        'complaint': {
            'complaint_id': 'CMP789012',
            'status': 'In Progress',
            'work_completed': 60,
            'officer_remark': 'Site visit scheduled',
            'deadline': datetime.now().date() + timedelta(days=7)
        }
    }
    
    return render(request, 'application-status.html', context)


@kiosk_login_required
def building_plan(request):
    if request.method == 'POST':
        owner_name = sanitize_input(request.POST.get('owner_name'), 100)
        property_address = sanitize_input(request.POST.get('property_address'), 500)
        survey_number = sanitize_input(request.POST.get('survey_number'), 50)
        plot_area = sanitize_input(request.POST.get('plot_area'))
        building_type = sanitize_input(request.POST.get('building_type'), 20)
        num_floors = sanitize_input(request.POST.get('num_floors'), 2)
        building_plan = request.FILES.get('building_plan')
        
        if not all([owner_name, property_address, survey_number, plot_area, building_type, num_floors]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'building-plan.html')
        
        if not building_plan:
            messages.error(request, 'Please upload the building plan file')
            return render(request, 'building-plan.html')
        
        # Validate file
        is_valid_ext, ext = validate_file_extension(building_plan.name, ['.pdf', '.dwg'])
        if not is_valid_ext:
            messages.error(request, 'Only PDF and DWG files are allowed')
            return render(request, 'building-plan.html')
        
        is_valid_size, size = validate_file_size(building_plan, 25)
        if not is_valid_size:
            messages.error(request, 'File size exceeds 25MB limit')
            return render(request, 'building-plan.html')
        
        ref_number = f"BLD{random.randint(100000, 999999)}"
        messages.success(request, f'Building plan application submitted successfully! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'building-plan.html')


# ================= GAS SERVICES =================

@kiosk_login_required
def gas_services(request):
    return render(request, 'gas-services.html')


@kiosk_login_required
def gas_subsidy(request):
    if request.method == 'POST':
        action = sanitize_input(request.POST.get('action'))
        
        if action == 'fetch':
            consumer_no = sanitize_input(request.POST.get('consumer_no'), 20)
            
            if not consumer_no:
                messages.error(request, 'Please enter consumer number')
                return render(request, 'gas-subsidy.html')
            
            context = {
                'show_subsidy': True,
                'consumer_no': consumer_no,
                'status': 'Active' if random.choice([True, False]) else 'Inactive',
                'amount_per_cylinder': '200',
                'total_cylinders': '12',
                'remaining_cylinders': random.randint(0, 12),
                'next_eligibility': (datetime.now().date() + timedelta(days=30)).strftime('%d %b %Y'),
                'bank_account': 'XXXXXX1234'
            }
            return render(request, 'gas-subsidy.html', context)
    
    return render(request, 'gas-subsidy.html')


@kiosk_login_required
def gas_new_connection(request):
    if request.method == 'POST':
        full_name = sanitize_input(request.POST.get('full_name'), 100)
        address = sanitize_input(request.POST.get('address'), 500)
        mobile = sanitize_input(request.POST.get('mobile'), 10)
        document_type = sanitize_input(request.POST.get('document_type'), 50)
        
        if not all([full_name, address, mobile, document_type]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'gas-new-connection.html')
        
        if not mobile.isdigit() or len(mobile) != 10:
            messages.error(request, 'Please enter a valid 10-digit mobile number')
            return render(request, 'gas-new-connection.html')
        
        ref_number = f"GAS{random.randint(100000, 999999)}"
        messages.success(request, f'New gas connection application submitted! Reference: {ref_number}')
        return redirect('gas-services')
    
    return render(request, 'gas-new-connection.html')


@kiosk_login_required
def gas_cylinder_booking(request):
    if request.method == 'POST':
        cylinder_type = sanitize_input(request.POST.get('cylinder_type'), 20)
        cylinder_price = sanitize_input(request.POST.get('cylinder_price_hidden'))
        
        if not cylinder_type:
            messages.error(request, 'Please select a cylinder type')
            return render(request, 'gas-cylinder-booking.html')
        
        ref_number = f"BOOK{random.randint(100000, 999999)}"
        messages.success(request, f'Cylinder booked successfully! Reference: {ref_number}')
        return redirect('gas-services')
    
    return render(request, 'gas-cylinder-booking.html')


@kiosk_login_required
def gas_consumer_lookup(request):
    if request.method == 'POST':
        aadhaar_number = sanitize_input(request.POST.get('aadhaar_number'), 12)
        
        if not aadhaar_number or len(aadhaar_number) != 12:
            messages.error(request, 'Please enter a valid 12-digit Aadhaar number')
            return render(request, 'gas-consumer-lookup.html')
        
        # Validate Aadhaar
        is_valid, message = validate_aadhaar(aadhaar_number)
        if not is_valid:
            messages.error(request, message)
            return render(request, 'gas-consumer-lookup.html')
        
        # Simulate consumer lookup
        context = {
            'show_result': True,
            'consumer': {
                'consumer_no': '1234 5678 9012',
                'name': 'Rajesh Kumar',
                'address': '123, Gandhi Nagar',
                'distributor': 'HP Gas - Indane',
                'status': 'Active',
                'last_booking': '15 Feb 2026'
            }
        }
        return render(request, 'gas-consumer-lookup.html', context)
    
    return render(request, 'gas-consumer-lookup.html')


@kiosk_login_required
def gas_complaint(request):
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number', '123456789012'), 20)
        complaint_type = sanitize_input(request.POST.get('complaint_type'), 50)
        description = sanitize_input(request.POST.get('description'), 1000)
        
        if not complaint_type:
            messages.error(request, 'Please select a complaint type')
            return render(request, 'gas-complaint.html')
        
        if not description or description.strip() == '':
            messages.error(request, 'Please describe your complaint')
            return render(request, 'gas-complaint.html')
        
        if len(description.strip()) < 10:
            messages.error(request, 'Please provide a more detailed description (minimum 10 characters)')
            return render(request, 'gas-complaint.html')
        
        ref_number = f"CMP{random.randint(100000, 999999)}"
        messages.success(request, f'Complaint registered successfully! Reference: {ref_number}')
        return redirect('gas-services')
    
    return render(request, 'gas-complaint.html')


@kiosk_login_required
def gas_bookings_status(request):
    context = {}
    
    if request.method == 'POST':
        reference_number = sanitize_input(request.POST.get('reference_number'), 20)
        
        if not reference_number:
            messages.error(request, 'Please enter a reference number')
            return render(request, 'gas-booking-status.html', context)
        
        today = datetime.now().date()
        
        # Simulate different booking statuses
        if reference_number.upper() == 'CYL251234':
            booking = {
                'reference_number': 'CYL251234',
                'booked_date': '22 Feb 2026, 10:30 AM',
                'expected_delivery': 'Today (25 Feb) by 6 PM',
                'delivery_person': 'Ramesh (98765 43210)',
                'cylinder_type': '14.2 kg Domestic Cylinder',
                'status': 'out_for_delivery'
            }
        elif reference_number.upper() == 'CYL251235':
            booking = {
                'reference_number': 'CYL251235',
                'booked_date': '20 Feb 2026, 9:15 AM',
                'expected_delivery': '23 Feb 2026',
                'actual_delivery': '23 Feb 2026, 11:30 AM',
                'delivery_person': 'Suresh (98765 43211)',
                'cylinder_type': '19 kg Commercial Cylinder',
                'status': 'delivered'
            }
        elif reference_number.upper() == 'CYL251236':
            booking = {
                'reference_number': 'CYL251236',
                'booked_date': '24 Feb 2026, 2:45 PM',
                'expected_delivery': '26 Feb 2026 by 6 PM',
                'cylinder_type': '5 kg Domestic Cylinder',
                'status': 'processed'
            }
        else:
            # Generate random booking for any reference
            booking = {
                'reference_number': reference_number,
                'booked_date': today.strftime('%d %b %Y') + ', 10:30 AM',
                'expected_delivery': (today + timedelta(days=2)).strftime('%d %b %Y') + ' by 6 PM',
                'delivery_person': 'Delivery team will be assigned soon',
                'cylinder_type': '14.2 kg Domestic Cylinder',
                'status': random.choice(['pending', 'processed', 'out_for_delivery'])
            }
        
        context['booking'] = booking
    
    return render(request, 'gas-booking-status.html', context)


@kiosk_login_required
def gas_bill_payment(request):
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number'), 20)
        amount = sanitize_input(request.POST.get('amount'))
        payment_method = sanitize_input(request.POST.get('payment_method', 'upi'), 10)
        
        transaction_id = f"GAS{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
        messages.success(request, f'Gas bill payment of ₹{amount} successful! Transaction ID: {transaction_id}')
        return redirect('gas-services')
    
    return render(request, 'gas-bill-payment.html')


# ================= TRANSPORT & REVENUE SERVICES =================

@kiosk_login_required
def transport_services(request):
    return render(request, 'under-development.html')


@kiosk_login_required
def revenue_services(request):
    return render(request, 'under-development.html')


# ================= PAYMENTS =================

@kiosk_login_required
def payment_history(request):
    filter_param = sanitize_input(request.GET.get('filter', 'all'), 20)
    
    # Sample payment data - in production, fetch from database
    payments = [
        {
            'reference_no': 'PAY123456',
            'service': 'electricity',
            'service_name': 'Electricity Bill',
            'date': datetime.now() - timedelta(days=2),
            'amount': 1250.00,
            'status': 'success'
        },
        {
            'reference_no': 'PAY123457',
            'service': 'water',
            'service_name': 'Water Bill',
            'date': datetime.now() - timedelta(days=5),
            'amount': 450.00,
            'status': 'success'
        },
        {
            'reference_no': 'PAY123458',
            'service': 'gas',
            'service_name': 'Gas Bill',
            'date': datetime.now() - timedelta(days=7),
            'amount': 856.00,
            'status': 'success'
        },
        {
            'reference_no': 'PAY123459',
            'service': 'property_tax',
            'service_name': 'Property Tax',
            'date': datetime.now() - timedelta(days=10),
            'amount': 3450.00,
            'status': 'success'
        },
        {
            'reference_no': 'PAY123460',
            'service': 'professional_tax',
            'service_name': 'Professional Tax',
            'date': datetime.now() - timedelta(days=12),
            'amount': 1250.00,
            'status': 'success'
        }
    ]
    
    # Filter payments
    if filter_param != 'all':
        payments = [p for p in payments if p['service'] == filter_param]
    
    context = {
        'payments': payments,
        'filter': filter_param
    }
    
    return render(request, 'payment-history.html', context)


@kiosk_login_required
def receipt_print(request):
    if request.method == 'POST':
        receipt_ref = sanitize_input(request.POST.get('receipt_ref'), 20)
        
        # In production, fetch receipt from database
        receipt = {
            'id': random.randint(1000, 9999),
            'receipt_no': receipt_ref or f'RCPT{random.randint(100000, 999999)}',
            'datetime': datetime.now().strftime('%d %b %Y, %I:%M %p'),
            'service': '⚡ Electricity Bill',
            'consumer_no': '1234 5678 9012',
            'bill_period': 'Jan 2026',
            'payment_mode': 'UPI',
            'transaction_id': f'TXN{datetime.now().strftime("%y%m%d%H%M%S")}',
            'amount': '1,250.00'
        }
        
        return render(request, 'receipt-print.html', {'receipt': receipt})
    
    return redirect('payment-history')


# ================= OTHER SERVICES / PAGES =================

@kiosk_login_required
def birth_certificate(request):
    if request.method == 'POST':
        child_name = sanitize_input(request.POST.get('child_name'), 100)
        dob = sanitize_input(request.POST.get('dob'), 10)
        gender = sanitize_input(request.POST.get('gender'), 10)
        birth_place = sanitize_input(request.POST.get('birth_place'), 100)
        father_name = sanitize_input(request.POST.get('father_name'), 100)
        mother_name = sanitize_input(request.POST.get('mother_name'), 100)
        permanent_address = sanitize_input(request.POST.get('permanent_address'), 500)
        
        if not all([child_name, dob, gender, birth_place, father_name, mother_name, permanent_address]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'birth-certificate.html')
        
        ref_number = f"BRTH{random.randint(100000, 999999)}"
        messages.success(request, f'Birth certificate application submitted successfully! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'birth-certificate.html')


@kiosk_login_required
def death_certificate(request):
    if request.method == 'POST':
        deceased_name = sanitize_input(request.POST.get('deceased_name'), 100)
        date_of_death = sanitize_input(request.POST.get('date_of_death'), 10)
        place_of_death = sanitize_input(request.POST.get('place_of_death'), 100)
        gender = sanitize_input(request.POST.get('gender'), 10)
        father_name = sanitize_input(request.POST.get('father_name'), 100)
        mother_name = sanitize_input(request.POST.get('mother_name'), 100)
        permanent_address = sanitize_input(request.POST.get('permanent_address'), 500)
        cause_of_death = sanitize_input(request.POST.get('cause_of_death'), 500)
        
        if not all([deceased_name, date_of_death, place_of_death, gender, father_name, mother_name, permanent_address, cause_of_death]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'death-certificate.html')
        
        from datetime import date
        if date_of_death:
            try:
                death_date = date.fromisoformat(date_of_death)
                if death_date > date.today():
                    messages.error(request, 'Date of death cannot be in the future')
                    return render(request, 'death-certificate.html')
            except ValueError:
                messages.error(request, 'Invalid date format')
                return render(request, 'death-certificate.html')
        
        ref_number = f"DTH{random.randint(100000, 999999)}"
        messages.success(request, f'Death certificate application submitted successfully! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'death-certificate.html')


@kiosk_login_required
def marriage_registration(request):
    if request.method == 'POST':
        groom_name = sanitize_input(request.POST.get('groom_name'), 100)
        groom_dob = sanitize_input(request.POST.get('groom_dob'), 10)
        groom_aadhaar = sanitize_input(request.POST.get('groom_aadhaar'), 12)
        groom_father_name = sanitize_input(request.POST.get('groom_father_name'), 100)
        bride_name = sanitize_input(request.POST.get('bride_name'), 100)
        bride_dob = sanitize_input(request.POST.get('bride_dob'), 10)
        bride_aadhaar = sanitize_input(request.POST.get('bride_aadhaar'), 12)
        bride_father_name = sanitize_input(request.POST.get('bride_father_name'), 100)
        marriage_date = sanitize_input(request.POST.get('marriage_date'), 10)
        marriage_place = sanitize_input(request.POST.get('marriage_place'), 100)
        marriage_type = sanitize_input(request.POST.get('marriage_type'), 50)
        witness1_name = sanitize_input(request.POST.get('witness1_name'), 100)
        witness2_name = sanitize_input(request.POST.get('witness2_name'), 100)
        
        if not all([groom_name, bride_name, marriage_date, marriage_place, marriage_type]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'marriage-registration.html')
        
        # Validate Aadhaar if provided
        if groom_aadhaar:
            is_valid, message = validate_aadhaar(groom_aadhaar)
            if not is_valid:
                messages.error(request, f'Groom Aadhaar: {message}')
                return render(request, 'marriage-registration.html')
        
        if bride_aadhaar:
            is_valid, message = validate_aadhaar(bride_aadhaar)
            if not is_valid:
                messages.error(request, f'Bride Aadhaar: {message}')
                return render(request, 'marriage-registration.html')
        
        ref_number = f"MAR{random.randint(100000, 999999)}"
        messages.success(request, f'Marriage registration submitted successfully! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'marriage-registration.html')


# ================= DOCUMENT UPLOADS =================

@kiosk_login_required
def document_upload_qr_view(request):
    if request.method == 'POST':
        session_id = sanitize_input(request.POST.get('session_id'), 50)
        document_count = sanitize_input(request.POST.get('document_count', '0'), 5)
        
        try:
            doc_count = int(document_count)
        except ValueError:
            doc_count = 0
        
        if doc_count > 0:
            messages.success(request, f'Successfully received {doc_count} documents via QR upload!')
        else:
            messages.success(request, 'Documents received successfully via QR upload!')
        
        return redirect('menu')
    
    import uuid
    session_id = str(uuid.uuid4())
    context = {'session_id': session_id}
    
    return render(request, 'document-upload-qr.html', context)


@kiosk_login_required
def document_upload_pen_view(request):
    if request.method == 'POST':
        if request.FILES:
            uploaded_files = request.FILES.getlist('files')
            
            if not uploaded_files:
                messages.error(request, 'No files were selected for upload')
                return render(request, 'document-upload-pen.html')
            
            max_files = 10
            if len(uploaded_files) > max_files:
                messages.error(request, f'Maximum {max_files} files allowed. You uploaded {len(uploaded_files)} files.')
                return render(request, 'document-upload-pen.html')
            
            allowed_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
            max_size_mb = 25
            
            valid_files = []
            errors = []
            
            for file in uploaded_files:
                # Validate file extension
                is_valid_ext, ext = validate_file_extension(file.name, allowed_extensions)
                if not is_valid_ext:
                    errors.append(f"{file.name}: Invalid file type. Only PDF, JPG, PNG allowed.")
                    continue
                
                # Validate file size
                is_valid_size, size = validate_file_size(file, max_size_mb)
                if not is_valid_size:
                    errors.append(f"{file.name}: File size exceeds {max_size_mb}MB limit.")
                    continue
                
                valid_files.append(file)
            
            if errors:
                for error in errors:
                    messages.error(request, error)
                return render(request, 'document-upload-pen.html')
            
            # In production, save files to database/media
            file_names = [f.name for f in valid_files]
            
            messages.success(request, f'Successfully uploaded {len(valid_files)} files!')
            
        else:
            file_names = request.POST.get('file_names', '')
            if file_names:
                file_count = len(file_names.split(','))
                messages.success(request, f'Successfully uploaded {file_count} files!')
            else:
                messages.error(request, 'No files were selected for upload')
                return render(request, 'document-upload-pen.html')
        
        return redirect('menu')
    
    return render(request, 'document-upload-pen.html')


@kiosk_login_required
def document_upload_camera_view(request):
    if request.method == 'POST':
        images_count = sanitize_input(request.POST.get('images_count'), 5)
        images_data = request.POST.get('images_data')
        
        if not images_count or int(images_count) == 0:
            messages.error(request, 'No images were captured')
            return render(request, 'document-upload-camera.html')
        
        try:
            images_list = json.loads(images_data)
            saved_images = []
            
            for i, image_data in enumerate(images_list):
                format, imgstr = image_data.split(';base64,')
                ext = format.split('/')[-1]
                file_name = f"camera_capture_{request.session.get('aadhaar_number')}_{i+1}.{ext}"
                file_data = ContentFile(base64.b64decode(imgstr), name=file_name)
                saved_images.append(file_name)
            
            messages.success(request, f'Successfully uploaded {len(saved_images)} images!')
            
        except Exception as e:
            messages.error(request, f'Error uploading images: {str(e)}')
            return render(request, 'document-upload-camera.html')
        
        return redirect('menu')
    
    return render(request, 'document-upload-camera.html')


@kiosk_login_required
def grievance(request):
    if request.method == 'POST':
        name = sanitize_input(request.POST.get('name'), 100)
        mobile = sanitize_input(request.POST.get('mobile'), 10)
        location = sanitize_input(request.POST.get('location'), 200)
        description = sanitize_input(request.POST.get('description'), 1000)
        department = sanitize_input(request.POST.get('department'), 50)
        
        if not all([name, mobile, location, description, department]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'grievance.html')
        
        if not mobile.isdigit() or len(mobile) != 10:
            messages.error(request, 'Please enter a valid 10-digit mobile number')
            return render(request, 'grievance.html')
        
        ref_number = f"GRV{random.randint(100000, 999999)}"
        messages.success(request, f'Grievance registered successfully! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'grievance.html')


# ================= UNDER DEVELOPMENT =================

@kiosk_login_required
def under_development(request):
    """View for under development pages"""
    return render(request, 'under-development.html')


# ================= API ENDPOINTS =================

@csrf_exempt
@rate_limit(max_attempts=30, time_window=60, key_prefix='api_load_cost')
def api_calculate_load_cost(request):
    """API endpoint to calculate load enhancement cost"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            current_load = float(data.get('current_load', 3))
            requested_load = float(data.get('requested_load', 0))
            
            if requested_load <= current_load:
                return JsonResponse({'error': 'Requested load must be greater than current load'}, status=400)
            
            additional_load = requested_load - current_load
            base_fee = 1500
            additional_fee = additional_load * 800
            subtotal = base_fee + additional_fee
            gst = subtotal * 0.18
            total = subtotal + gst
            
            return JsonResponse({
                'base_fee': base_fee,
                'additional_fee': additional_fee,
                'subtotal': subtotal,
                'gst': gst,
                'total': total
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
@rate_limit(max_attempts=30, time_window=60, key_prefix='api_meter_cost')
def api_calculate_meter_cost(request):
    """API endpoint to calculate meter replacement cost"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            meter_price = float(data.get('meter_price', 1200))
            additional_services = data.get('additional_services', [])
            
            installation_fee = 500
            additional_cost = 0
            
            if 'calibration' in additional_services:
                additional_cost += 300
            if 'wiring' in additional_services:
                additional_cost += 500
            if 'seal' in additional_services:
                additional_cost += 100
            
            subtotal = meter_price + installation_fee + additional_cost
            gst = subtotal * 0.18
            total = subtotal + gst
            
            return JsonResponse({
                'meter_price': meter_price,
                'installation_fee': installation_fee,
                'additional_cost': additional_cost,
                'subtotal': subtotal,
                'gst': gst,
                'total': total
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


# ================= ERROR HANDLERS =================

def custom_404(request, exception):
    """Custom 404 error handler"""
    return render(request, '404.html', status=404)


def test_404(request):
    """Test view to check 404 page"""
    return render(request, '404.html')