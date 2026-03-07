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
from datetime import datetime, timedelta  # Fixed import
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

logger = logging.getLogger(__name__)


# ================= OTP UTILITY FUNCTIONS =================

def generate_otp(length=6):
    """Generate a random OTP of specified length"""
    return ''.join([str(random.randint(0, 9)) for _ in range(length)])


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


def verify_otp(stored_otp, entered_otp, otp_timestamp):
    """
    Verify OTP and check expiry (5 minutes)
    """
    
    if not stored_otp or not entered_otp:
        return False, "OTP missing"
    
    if stored_otp != entered_otp:
        return False, "Invalid OTP"
    
    # Check if OTP is expired (5 minutes)
    expiry_time = otp_timestamp + timedelta(minutes=5)
    if datetime.now() > expiry_time:
        return False, "OTP expired"
    
    return True, "OTP verified"


# ================= CORE / AUTH =================

def index(request):
    return render(request, 'index.html')


def auth(request):
    """Aadhaar authentication page"""
    # Clear any existing messages
    storage = messages.get_messages(request)
    storage.used = True
    
    # CRITICAL: If there's ANY query parameter, redirect to clean URL
    if request.GET:
        return redirect('auth')
    
    if request.method == 'POST':
        aadhaar_number = request.POST.get('aadhaar_number')
        
        # Validate Aadhaar format
        if not aadhaar_number or len(aadhaar_number) != 12 or not aadhaar_number.isdigit():
            messages.error(request, 'Please enter a valid 12-digit Aadhaar number')
            return render(request, 'auth.html')
        
        try:
            # Check if consumer exists in database
            consumer = Consumer.objects.get(aadhaar_number=aadhaar_number, is_active=True)
            
            # Store in session
            request.session['aadhaar_number'] = aadhaar_number
            request.session['consumer_id'] = consumer.id
            
            # Generate OTP
            otp = generate_otp(6)
            request.session['otp'] = otp
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
                    ip_address=request.META.get('REMOTE_ADDR', ''),
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
                ip_address=request.META.get('REMOTE_ADDR', ''),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
            
            return render(request, 'auth.html')
        except Exception as e:
            logger.error(f"Error during authentication: {str(e)}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'auth.html')
    
    # GET request - show the Aadhaar entry page
    return render(request, 'auth.html')


def otp(request):
    """OTP verification page"""
    # Check if aadhaar is in session
    aadhaar_number = request.session.get('aadhaar_number')
    consumer_id = request.session.get('consumer_id')
    stored_otp = request.session.get('otp')
    otp_timestamp_str = request.session.get('otp_timestamp')
    
    if not aadhaar_number or not consumer_id or not stored_otp:
        messages.error(request, 'Session expired. Please enter Aadhaar again.')
        return redirect('auth')
    
    # Parse timestamp
    try:
        otp_timestamp = datetime.fromisoformat(otp_timestamp_str)
    except:
        otp_timestamp = datetime.now() - timedelta(minutes=6)  # Force expiry
    
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        
        # Get attempt count
        attempts = request.session.get('otp_attempts', 0)
        request.session['otp_attempts'] = attempts + 1
        
        if attempts >= 3:
            messages.error(request, 'Too many failed attempts. Please request new OTP.')
            return redirect('resend-otp')
        
        # Verify OTP
        is_valid, message = verify_otp(stored_otp, entered_otp, otp_timestamp)
        
        if is_valid:
            # OTP verified successfully
            request.session['aadhaar_verified'] = True
            request.session['otp_verified'] = True
            
            # Update consumer last login
            try:
                consumer = Consumer.objects.get(id=consumer_id)
                consumer.last_login = datetime.now()
                consumer.save()
                
                # FIX: Handle UserSession creation properly
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
                    existing_session.ip_address = request.META.get('REMOTE_ADDR', '')
                    existing_session.user_agent = request.META.get('HTTP_USER_AGENT', '')
                    existing_session.is_active = True
                    existing_session.save()
                    logger.info(f"✅ Updated existing session: {session_key}")
                else:
                    # Create new session
                    UserSession.objects.create(
                        consumer=consumer,
                        session_key=session_key,
                        ip_address=request.META.get('REMOTE_ADDR', ''),
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
                request.session.pop('otp', None)
                request.session.pop('otp_timestamp', None)
                
                messages.success(request, 'OTP verified successfully!')
                
            except Consumer.DoesNotExist:
                messages.error(request, 'Consumer record not found.')
                return redirect('auth')
            
            return redirect('menu')
        else:
            messages.error(request, message)
    
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


def resend_otp(request):
    """Resend OTP"""
    if request.method == 'POST':
        aadhaar_number = request.session.get('aadhaar_number')
        consumer_id = request.session.get('consumer_id')
        
        if not aadhaar_number or not consumer_id:
            messages.error(request, 'Session expired. Please login again.')
            return redirect('auth')
        
        try:
            consumer = Consumer.objects.get(id=consumer_id, aadhaar_number=aadhaar_number)
            
            # Generate new OTP
            otp = generate_otp(6)
            request.session['otp'] = otp
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
                    ip_address=request.META.get('REMOTE_ADDR', ''),
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


def menu(request):
    """Main menu after authentication"""
    # Check if user is verified
    if not request.session.get('aadhaar_verified') or not request.session.get('otp_verified'):
        messages.error(request, 'Please login first')
        return redirect('auth')
    
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

def electricity_services(request):
    # Check if user is verified
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    # Add some context data to ensure the page renders
    context = {
        'page_title': 'Electricity Services',
        'current_date': datetime.now().strftime('%d %b %Y'),
    }
    return render(request, 'electricity-services.html', context)


def electricity_bill_payment(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    context = {}
    
    if request.method == 'POST':
        action = request.POST.get('action')
        consumer_number = request.POST.get('consumer_number')
        bill_amount = request.POST.get('bill_amount')
        
        # FIELDS for payment method
        payment_method = request.POST.get('payment_method')  # 'upi' or 'atm'
        upi_id = request.POST.get('upi_id')
        card_number = request.POST.get('card_number')
        cvv = request.POST.get('cvv')
        pin = request.POST.get('pin')
        
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
            
            messages.success(request, f'Payment of ₹{bill_amount} for consumer {consumer_number} successful! Transaction ID: {transaction_id}')
            return redirect('payment-history')
        
        elif action == 'fetch':
            context['show_bill'] = True
            context['consumer_number'] = consumer_number
    
    return render(request, 'electricity-bill-payment.html', context)


def electricity_duplicate_bill(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    context = {}
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'download':
            bill_id = request.POST.get('bill_id')
            bill_month = request.POST.get('bill_month')
            
            if bill_id and bill_month:
                messages.success(request, f'Bill for {bill_month} downloaded successfully!')
            
            return redirect('electricity-duplicate-bill')
        
        elif action == 'pay':
            # Redirect to payment page with bill details
            bill_month = request.POST.get('bill_month')
            bill_amount = request.POST.get('bill_amount')
            bill_number = request.POST.get('bill_number')
            
            # Store in session for payment page
            request.session['pending_payment'] = {
                'service': 'electricity',
                'consumer_no': request.POST.get('consumer_number'),
                'amount': bill_amount,
                'bill_number': bill_number,
                'bill_month': bill_month
            }
            
            return redirect('electricity-bill-payment')
        
        else:  # Search action
            consumer_number = request.POST.get('consumer_number')
            
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


def electricity_solar(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        consumer_number = request.POST.get('consumer_number')
        solar_capacity = request.POST.get('solar_capacity')
        roof_area = request.POST.get('roof_area')
        
        if not consumer_number or not solar_capacity:
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'electricity-solar.html')
        
        ref_number = f"SOLAR{random.randint(100000, 999999)}"
        messages.success(request, f'Solar net metering application submitted! Reference: {ref_number}')
        return redirect('electricity-services')
    
    return render(request, 'electricity-solar.html')


def electricity_new_connection(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        full_name = request.POST.get('full_name')
        address = request.POST.get('address')
        property_type = request.POST.get('property_type')
        load_required = request.POST.get('load_required')
        mobile_number = request.POST.get('mobile_number')
        
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


def electricity_name_transfer(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    context = {}
    
    if request.method == 'POST':
        consumer_number = request.POST.get('consumer_number', '123456789012')
        new_owner_name = request.POST.get('new_owner_name')
        new_owner_aadhaar = request.POST.get('new_owner_aadhaar')
        relationship = request.POST.get('relationship')
        
        # NEW FIELDS
        new_owner_phone = request.POST.get('new_owner_phone')
        new_owner_email = request.POST.get('new_owner_email')
        transfer_fee = request.POST.get('transfer_fee', 500)
        
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
        
        aadhaar_clean = new_owner_aadhaar.replace(' ', '')
        if not (aadhaar_clean.isdigit() and len(aadhaar_clean) == 12):
            messages.error(request, 'Please enter a valid 12-digit Aadhaar number')
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


def electricity_meter_replacement(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        consumer_number = request.POST.get('consumer_number', '123456789012')
        meter_type = request.POST.get('meter_type')
        meter_price = request.POST.get('meter_price')
        reason = request.POST.get('reason')
        preferred_date = request.POST.get('preferred_date')
        
        # NEW FIELDS
        preferred_time = request.POST.get('preferred_time', '09:00-12:00')
        additional_services = request.POST.get('additional_services', '')
        
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


def electricity_load_enhancement(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        consumer_number = request.POST.get('consumer_number', '123456789012')
        current_load = request.POST.get('current_load', '3')
        requested_load = request.POST.get('requested_load')
        reason = request.POST.get('reason')
        
        # NEW FIELD
        reason_details = request.POST.get('reason_details', '')
        
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


def electricity_complaint(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        consumer_number = request.POST.get('consumer_number', '123456789012')
        complaint_type = request.POST.get('complaint_type')
        complaint_description = request.POST.get('complaint_description')
        
        # NEW FIELDS
        complaint_priority = request.POST.get('complaint_priority', 'Normal')
        contact_phone = request.POST.get('contact_phone')
        
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

def water_bill(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        consumer_no = request.POST.get('consumer_no')
        
        if action == 'pay':
            bill_amount = request.POST.get('bill_amount')
            payment_method = request.POST.get('payment_method', 'upi')
            
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

def municipal_services(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'municipal-services.html')


def trade_license(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        business_name = request.POST.get('business_name')
        business_type = request.POST.get('business_type')
        owner_name = request.POST.get('owner_name')
        address = request.POST.get('address')
        gst_number = request.POST.get('gst_number')
        
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


def property_tax(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        property_id = request.POST.get('property_id')
        
        if action == 'pay':
            tax_amount = request.POST.get('tax_amount')
            payment_method = request.POST.get('payment_method', 'upi')
            
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


def professional_tax(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        ptin = request.POST.get('ptin')
        
        if action == 'pay':
            tax_amount = request.POST.get('tax_amount')
            payment_method = request.POST.get('payment_method', 'upi')
            
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


def application_status(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
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


def building_plan(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        owner_name = request.POST.get('owner_name')
        property_address = request.POST.get('property_address')
        survey_number = request.POST.get('survey_number')
        plot_area = request.POST.get('plot_area')
        building_type = request.POST.get('building_type')
        num_floors = request.POST.get('num_floors')
        building_plan = request.FILES.get('building_plan')
        
        if not all([owner_name, property_address, survey_number, plot_area, building_type, num_floors]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'building-plan.html')
        
        if not building_plan:
            messages.error(request, 'Please upload the building plan file')
            return render(request, 'building-plan.html')
        
        if building_plan.size > 25 * 1024 * 1024:
            messages.error(request, 'File size exceeds 25MB limit')
            return render(request, 'building-plan.html')
        
        allowed_extensions = ['.pdf', '.dwg']
        file_extension = os.path.splitext(building_plan.name)[1].lower()
        if file_extension not in allowed_extensions:
            messages.error(request, 'Only PDF and DWG files are allowed')
            return render(request, 'building-plan.html')
        
        ref_number = f"BLD{random.randint(100000, 999999)}"
        messages.success(request, f'Building plan application submitted successfully! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'building-plan.html')


# ================= GAS SERVICES =================

def gas_services(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'gas-services.html')


def gas_subsidy(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'fetch':
            consumer_no = request.POST.get('consumer_no')
            
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


def gas_new_connection(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        full_name = request.POST.get('full_name')
        address = request.POST.get('address')
        mobile = request.POST.get('mobile')
        document_type = request.POST.get('document_type')
        
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


def gas_cylinder_booking(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        cylinder_type = request.POST.get('cylinder_type')
        cylinder_price = request.POST.get('cylinder_price_hidden')
        
        if not cylinder_type:
            messages.error(request, 'Please select a cylinder type')
            return render(request, 'gas-cylinder-booking.html')
        
        ref_number = f"BOOK{random.randint(100000, 999999)}"
        messages.success(request, f'Cylinder booked successfully! Reference: {ref_number}')
        return redirect('gas-services')
    
    return render(request, 'gas-cylinder-booking.html')


def gas_consumer_lookup(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        aadhaar_number = request.POST.get('aadhaar_number')
        
        if not aadhaar_number or len(aadhaar_number) != 12:
            messages.error(request, 'Please enter a valid 12-digit Aadhaar number')
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


def gas_complaint(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        consumer_number = request.POST.get('consumer_number', '123456789012')
        complaint_type = request.POST.get('complaint_type')
        description = request.POST.get('description')
        
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


def gas_bookings_status(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    context = {}
    
    if request.method == 'POST':
        reference_number = request.POST.get('reference_number')
        
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


def gas_bill_payment(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        consumer_number = request.POST.get('consumer_number')
        amount = request.POST.get('amount')
        payment_method = request.POST.get('payment_method', 'upi')
        
        transaction_id = f"GAS{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
        messages.success(request, f'Gas bill payment of ₹{amount} successful! Transaction ID: {transaction_id}')
        return redirect('gas-services')
    
    return render(request, 'gas-bill-payment.html')


# ================= TRANSPORT & REVENUE SERVICES =================

def transport_services(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'under-development.html')


def revenue_services(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'under-development.html')


# ================= PAYMENTS =================

def payment_history(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    filter_param = request.GET.get('filter', 'all')
    
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


def receipt_print(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        receipt_ref = request.POST.get('receipt_ref')
        
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

def birth_certificate(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        child_name = request.POST.get('child_name')
        dob = request.POST.get('dob')
        gender = request.POST.get('gender')
        birth_place = request.POST.get('birth_place')
        father_name = request.POST.get('father_name')
        mother_name = request.POST.get('mother_name')
        permanent_address = request.POST.get('permanent_address')
        
        if not all([child_name, dob, gender, birth_place, father_name, mother_name, permanent_address]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'birth-certificate.html')
        
        ref_number = f"BRTH{random.randint(100000, 999999)}"
        messages.success(request, f'Birth certificate application submitted successfully! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'birth-certificate.html')


def death_certificate(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        deceased_name = request.POST.get('deceased_name')
        date_of_death = request.POST.get('date_of_death')
        place_of_death = request.POST.get('place_of_death')
        gender = request.POST.get('gender')
        father_name = request.POST.get('father_name')
        mother_name = request.POST.get('mother_name')
        permanent_address = request.POST.get('permanent_address')
        cause_of_death = request.POST.get('cause_of_death')
        
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


def marriage_registration(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        groom_name = request.POST.get('groom_name')
        groom_dob = request.POST.get('groom_dob')
        groom_aadhaar = request.POST.get('groom_aadhaar')
        groom_father_name = request.POST.get('groom_father_name')
        bride_name = request.POST.get('bride_name')
        bride_dob = request.POST.get('bride_dob')
        bride_aadhaar = request.POST.get('bride_aadhaar')
        bride_father_name = request.POST.get('bride_father_name')
        marriage_date = request.POST.get('marriage_date')
        marriage_place = request.POST.get('marriage_place')
        marriage_type = request.POST.get('marriage_type')
        witness1_name = request.POST.get('witness1_name')
        witness2_name = request.POST.get('witness2_name')
        
        if not all([groom_name, bride_name, marriage_date, marriage_place, marriage_type]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'marriage-registration.html')
        
        # Validate Aadhaar if provided
        if groom_aadhaar and (len(groom_aadhaar) != 12 or not groom_aadhaar.isdigit()):
            messages.error(request, 'Please enter a valid 12-digit Aadhaar for groom')
            return render(request, 'marriage-registration.html')
        
        if bride_aadhaar and (len(bride_aadhaar) != 12 or not bride_aadhaar.isdigit()):
            messages.error(request, 'Please enter a valid 12-digit Aadhaar for bride')
            return render(request, 'marriage-registration.html')
        
        ref_number = f"MAR{random.randint(100000, 999999)}"
        messages.success(request, f'Marriage registration submitted successfully! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'marriage-registration.html')


# ================= DOCUMENT UPLOADS =================

def document_upload_qr_view(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        session_id = request.POST.get('session_id')
        document_count = request.POST.get('document_count', '0')
        
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


def document_upload_pen_view(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
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
            max_size_bytes = max_size_mb * 1024 * 1024
            
            valid_files = []
            errors = []
            
            for file in uploaded_files:
                file_extension = os.path.splitext(file.name)[1].lower()
                if file_extension not in allowed_extensions:
                    errors.append(f"{file.name}: Invalid file type. Only PDF, JPG, PNG allowed.")
                    continue
                
                if file.size > max_size_bytes:
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


def document_upload_camera_view(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        images_count = request.POST.get('images_count')
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


def grievance(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        name = request.POST.get('name')
        mobile = request.POST.get('mobile')
        location = request.POST.get('location')
        description = request.POST.get('description')
        department = request.POST.get('department')
        
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

def under_development(request):
    """View for under development pages"""
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'under-development.html')


# ================= API ENDPOINTS =================

@csrf_exempt
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