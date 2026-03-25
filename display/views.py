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
from django.db import IntegrityError, DatabaseError
from django.core.cache import cache
import traceback
import uuid

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
from .decorators import kiosk_login_required
from .utils.security import (
    generate_secure_otp, hash_otp, verify_otp_hash, 
    validate_aadhaar, sanitize_input,
    log_security_event, get_client_ip,
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
    """Language selection page"""
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
        aadhaar_number = sanitize_input(request.POST.get('aadhaar_number'), 12)
        
        # Simple Aadhaar format validation (just check if it's 12 digits)
        if not aadhaar_number or not aadhaar_number.isdigit() or len(aadhaar_number) != 12:
            messages.error(request, 'Please enter a valid 12-digit Aadhaar number')
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
                
                # Create audit log (don't fail if this errors)
                try:
                    AuditLog.objects.create(
                        consumer=consumer,
                        action='OTP_SENT',
                        model_name='Consumer',
                        object_id=consumer.id,
                        changes={'aadhaar': aadhaar_number[-4:]},
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                    )
                except Exception as e:
                    logger.error(f"Failed to create audit log: {e}")
                
                return redirect('otp')
            else:
                messages.error(request, f'Failed to send OTP: {message}')
                # Fallback - show OTP in console for testing
                messages.info(request, f'OTP for testing: {otp} (Check console)')
                print(f"\n⚠️ FALLBACK OTP: {otp}")
                return redirect('otp')
                
        except Consumer.DoesNotExist:
            messages.error(request, 'Aadhaar number not found in our records. Please contact support.')
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
        
        # Get attempt count (just for display, not for blocking)
        attempts = request.session.get('otp_attempts', 0)
        request.session['otp_attempts'] = attempts + 1
        
        # Verify OTP using hash
        is_valid, message = verify_otp(stored_otp_hash, entered_otp, otp_timestamp)
        
        if is_valid:
            # OTP verified successfully
            request.session['aadhaar_verified'] = True
            request.session['otp_verified'] = True
            
            try:
                consumer = Consumer.objects.get(id=consumer_id)
                consumer.last_login = datetime.now()
                consumer.save()
                
                # Create user session
                session_key = request.session.session_key
                
                # Deactivate any existing active sessions for this consumer
                UserSession.objects.filter(
                    consumer=consumer,
                    is_active=True
                ).update(is_active=False)
                
                # Create new session record
                UserSession.objects.create(
                    consumer=consumer,
                    session_key=session_key,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                )
                
                # Create notification
                try:
                    Notification.objects.create(
                        consumer=consumer,
                        notification_type='GENERAL',
                        title='Login Successful',
                        message=f'You have successfully logged in to Civic Kiosk at {datetime.now().strftime("%d %b %Y %I:%M %p")}'
                    )
                except Exception as e:
                    logger.error(f"Failed to create notification: {e}")
                
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
            otp = generate_secure_otp(6)
            otp_hash = hash_otp(otp)
            request.session['otp_hash'] = otp_hash
            request.session['otp_attempts'] = 0
            request.session['otp_timestamp'] = datetime.now().isoformat()
            
            # Send OTP via CircuitDigest
            success, message = send_otp_via_circuitdigest(consumer.mobile, otp, aadhaar_number)
            
            if success:
                messages.success(request, 'New OTP sent successfully to your registered mobile number')
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


@kiosk_login_required
def menu(request):
    """Main menu after authentication"""
    # Get consumer info for display
    consumer_id = request.session.get('consumer_id')
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        
        # Get unread notifications count
        notifications_count = Notification.objects.filter(consumer=consumer, is_read=False).count()
        
        # Get pending applications count across all services
        pending_count = 0
        
        # Electricity applications
        try:
            elec_consumer = ElectricityConsumer.objects.filter(consumer=consumer).first()
            if elec_consumer:
                pending_count += ElectricityComplaint.objects.filter(consumer=elec_consumer, status='PENDING').count()
                pending_count += LoadEnhancementRequest.objects.filter(consumer=elec_consumer, status='PENDING').count()
                pending_count += MeterReplacementRequest.objects.filter(consumer=elec_consumer, status='PENDING').count()
                pending_count += NameTransferRequest.objects.filter(consumer=elec_consumer, status='PENDING').count()
        except:
            pass
        
        # Gas applications
        try:
            gas_consumer = GasConsumer.objects.filter(consumer=consumer).first()
            if gas_consumer:
                pending_count += GasCylinderBooking.objects.filter(consumer=gas_consumer, status='PENDING').count()
                pending_count += GasComplaint.objects.filter(consumer=gas_consumer, status='PENDING').count()
        except:
            pass
        
        # Municipal applications
        pending_count += BuildingPlanApplication.objects.filter(consumer=consumer, status='PENDING').count()
        pending_count += Grievance.objects.filter(consumer=consumer, status='PENDING').count()
        pending_count += BirthCertificateApplication.objects.filter(consumer=consumer, status='PENDING').count()
        pending_count += DeathCertificateApplication.objects.filter(consumer=consumer, status='PENDING').count()
        
        context = {
            'consumer_name': consumer.name,
            'consumer_aadhaar': consumer.aadhaar_number[-4:],
            'consumer_phone': consumer.mobile[-4:],
            'notifications': notifications_count,
            'pending_applications': pending_count
        }
    except Consumer.DoesNotExist:
        context = {}
    
    return render(request, 'menu.html', context)


# ================= ELECTRICITY SERVICES =================

@kiosk_login_required
def electricity_services(request):
    """Main electricity services menu"""
    consumer_id = request.session.get('consumer_id')
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        # Get electricity consumer details if exists
        try:
            elec_consumer = ElectricityConsumer.objects.get(consumer=consumer)
            
            # Get pending applications count
            pending_complaints = ElectricityComplaint.objects.filter(consumer=elec_consumer, status='PENDING').count()
            pending_load = LoadEnhancementRequest.objects.filter(consumer=elec_consumer, status='PENDING').count()
            pending_meter = MeterReplacementRequest.objects.filter(consumer=elec_consumer, status='PENDING').count()
            pending_transfer = NameTransferRequest.objects.filter(consumer=elec_consumer, status='PENDING').count()
            
            context = {
                'page_title': 'Electricity Services',
                'current_date': datetime.now().strftime('%d %b %Y'),
                'consumer_number': elec_consumer.consumer_number,
                'has_connection': True,
                'pending_count': pending_complaints + pending_load + pending_meter + pending_transfer
            }
        except ElectricityConsumer.DoesNotExist:
            context = {
                'page_title': 'Electricity Services',
                'current_date': datetime.now().strftime('%d %b %Y'),
                'has_connection': False,
                'pending_count': 0
            }
    except:
        context = {
            'page_title': 'Electricity Services',
            'current_date': datetime.now().strftime('%d %b %Y')
        }
    
    return render(request, 'electricity-services.html', context)


@kiosk_login_required
def electricity_bill_payment(request):
    """Electricity bill payment page"""
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
            
            # Get consumer ID from session
            consumer_id = request.session.get('consumer_id')
            
            try:
                consumer = Consumer.objects.get(id=consumer_id)
                
                # Find electricity consumer
                elec_consumer = ElectricityConsumer.objects.filter(consumer_number=consumer_number).first()
                
                if elec_consumer:
                    # Find the bill
                    bill = ElectricityBill.objects.filter(
                        consumer=elec_consumer,
                        status='PENDING'
                    ).order_by('-bill_date').first()
                    
                    if bill:
                        # Generate transaction ID
                        transaction_id = f"TXN{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
                        
                        # Create payment record
                        payment = ElectricityPayment.objects.create(
                            bill=bill,
                            transaction_id=transaction_id,
                            amount=bill_amount,
                            payment_method=payment_method.upper(),
                            payment_details={'method': payment_method, 'details': payment_details},
                            status='SUCCESS'
                        )
                        
                        # Update bill status
                        bill.status = 'PAID'
                        bill.paid_amount = bill_amount
                        bill.save()
                        
                        # Create notification
                        Notification.objects.create(
                            consumer=consumer,
                            notification_type='PAYMENT_SUCCESS',
                            title='Electricity Bill Paid',
                            message=f'Payment of ₹{bill_amount} for bill {bill.bill_number} successful. Transaction ID: {transaction_id}'
                        )
                        
                        messages.success(request, f'Payment of ₹{bill_amount} for consumer {consumer_number} successful! Transaction ID: {transaction_id}')
                    else:
                        # No pending bill found, still process payment (for demo)
                        transaction_id = f"TXN{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
                        messages.success(request, f'Payment of ₹{bill_amount} for consumer {consumer_number} successful! Transaction ID: {transaction_id}')
                else:
                    # No electricity consumer found, still process payment (for demo)
                    transaction_id = f"TXN{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
                    messages.success(request, f'Payment of ₹{bill_amount} for consumer {consumer_number} successful! Transaction ID: {transaction_id}')
                    
            except Exception as e:
                logger.error(f"Error processing payment: {e}")
                # Fallback
                transaction_id = f"TXN{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
                messages.success(request, f'Payment of ₹{bill_amount} for consumer {consumer_number} successful! Transaction ID: {transaction_id}')
            
            return redirect('payment-history')
        
        elif action == 'fetch':
            context['show_bill'] = True
            context['consumer_number'] = consumer_number
    
    return render(request, 'electricity-bill-payment.html', context)


@kiosk_login_required
def electricity_duplicate_bill(request):
    """Duplicate bill download page"""
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
            
            # Fetch bills from database
            try:
                # Try to find electricity consumer
                elec_consumer = ElectricityConsumer.objects.filter(consumer_number=consumer_number).first()
                if elec_consumer:
                    # Get actual bills from database
                    bills_qs = ElectricityBill.objects.filter(consumer=elec_consumer).order_by('-bill_date')[:6]
                    bills = []
                    for bill in bills_qs:
                        bills.append({
                            'id': bill.id,
                            'month': bill.billing_period_end.strftime('%B %Y'),
                            'year': bill.billing_period_end.year,
                            'bill_date': bill.bill_date.strftime('%d %b %Y'),
                            'due_date': bill.due_date.strftime('%d %b %Y'),
                            'amount': str(bill.total_amount),
                            'bill_number': bill.bill_number,
                            'units': bill.units_consumed,
                            'status': bill.status
                        })
                else:
                    messages.error(request, 'Record not found. Please verify your details.')
                    context['show_results'] = False
                    bills = []
                    data = []
            except Exception as e:
                logger.error(f"Error fetching bills: {e}")
                bills = []
            
            context['bills'] = bills
            context['show_bills'] = True
            context['consumer_number'] = consumer_number
    
    return render(request, 'electricity-duplicate-bill.html', context)


@kiosk_login_required
def electricity_solar(request):
    """Solar net metering application"""
    consumer_id = request.session.get('consumer_id')
    
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number'), 20)
        solar_capacity = sanitize_input(request.POST.get('solar_capacity'))
        roof_area = sanitize_input(request.POST.get('roof_area'))
        
        if not consumer_number or not solar_capacity:
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'electricity-solar.html')
        
        # Generate reference number
        ref_number = f"SOLAR{random.randint(100000, 999999)}"
        
        # Save to database (create a SolarApplication model if needed)
        # For now, just log it
        try:
            consumer = Consumer.objects.get(id=consumer_id)
            AuditLog.objects.create(
                consumer=consumer,
                action='SOLAR_APPLICATION',
                model_name='Solar',
                object_id='',
                changes={'reference': ref_number, 'capacity': solar_capacity},
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='Solar Application Submitted',
                message=f'Your solar net metering application {ref_number} has been submitted successfully.'
            )
        except Exception as e:
            logger.error(f"Error logging solar application: {e}")
        
        messages.success(request, f'Solar net metering application submitted! Reference: {ref_number}')
        return redirect('electricity-services')
    
    return render(request, 'electricity-solar.html')


@kiosk_login_required
def electricity_new_connection(request):
    """New electricity connection application"""
    consumer_id = request.session.get('consumer_id')
    
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
        
        # Generate reference number
        ref_number = f"ELEC{random.randint(100000, 999999)}"
        
        try:
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Create electricity consumer record (pending status)
            elec_consumer = ElectricityConsumer.objects.create(
                consumer=consumer,
                consumer_number=ref_number,
                connection_type=property_type,
                sanctioned_load=load_value,
                connection_date=None,
                address=address
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='New Connection Application',
                message=f'Your new connection application {ref_number} has been submitted successfully.'
            )
            
            messages.success(request, f'New connection application submitted successfully! Reference: {ref_number}')
            
        except Consumer.DoesNotExist:
            messages.error(request, 'Consumer not found')
            return render(request, 'electricity-new-connection.html')
        except Exception as e:
            logger.error(f"Error creating new connection: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'electricity-new-connection.html')
        
        return redirect('electricity-services')
    
    return render(request, 'electricity-new-connection.html')


@kiosk_login_required
def electricity_name_transfer(request):
    """Name transfer request"""
    context = {}
    consumer_id = request.session.get('consumer_id')
    
    # Get current consumer details
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        
        # Get electricity consumer if exists
        try:
            elec_consumer = ElectricityConsumer.objects.get(consumer=consumer)
            context['current_owner'] = consumer.name
            context['consumer_number'] = elec_consumer.consumer_number
            context['address'] = elec_consumer.address
        except ElectricityConsumer.DoesNotExist:
            context['current_owner'] = consumer.name
            context['consumer_number'] = 'Not available'
            context['address'] = consumer.address
    except:
        context['current_owner'] = 'Rajesh Kumar'
        context['consumer_number'] = '123456789012'
        context['address'] = '123, Gandhi Nagar'
    
    context['transfer_fee'] = 500
    context['document_fee'] = 200
    context['total_fee'] = 826  # 500 + 200 + 18% GST
    
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number', '123456789012'), 20)
        new_owner_name = sanitize_input(request.POST.get('new_owner_name'), 100)
        new_owner_aadhaar = sanitize_input(request.POST.get('new_owner_aadhaar'), 12)
        relationship = sanitize_input(request.POST.get('relationship'), 50)
        
        # NEW FIELDS
        new_owner_phone = sanitize_input(request.POST.get('new_owner_phone'), 10)
        new_owner_email = sanitize_input(request.POST.get('new_owner_email'), 100)
        
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
        
        # Simple Aadhaar validation
        aadhaar_clean = new_owner_aadhaar.replace(' ', '')
        if not aadhaar_clean.isdigit() or len(aadhaar_clean) != 12:
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
        
        # Generate reference number
        ref_number = f"TRAN{random.randint(100000, 999999)}"
        
        try:
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Get or create electricity consumer
            elec_consumer, created = ElectricityConsumer.objects.get_or_create(
                consumer=consumer,
                defaults={
                    'consumer_number': consumer_number,
                    'connection_type': 'RESIDENTIAL',
                    'sanctioned_load': 3.0,
                    'address': consumer.address
                }
            )
            
            # Create name transfer request
            transfer = NameTransferRequest.objects.create(
                consumer=elec_consumer,
                request_number=ref_number,
                new_owner_name=new_owner_name,
                new_owner_aadhaar=aadhaar_clean,
                new_owner_phone=new_owner_phone,
                new_owner_email=new_owner_email,
                relationship=relationship,
                transfer_fee=500,
                document_fee=200,
                total_amount=826,
                status='PENDING'
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='Name Transfer Request',
                message=f'Your name transfer request {ref_number} has been submitted successfully.'
            )
            
            messages.success(request, f'Name transfer request submitted successfully! Reference: {ref_number}')
            
        except Exception as e:
            logger.error(f"Error creating name transfer: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'electricity-name-transfer.html', context)
        
        return redirect('electricity-services')
    
    return render(request, 'electricity-name-transfer.html', context)


@kiosk_login_required
def electricity_meter_replacement(request):
    """Meter replacement request"""
    consumer_id = request.session.get('consumer_id')
    
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
        
        # Generate reference number
        ref_number = f"METER{random.randint(100000, 999999)}"
        
        try:
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Get or create electricity consumer
            elec_consumer, created = ElectricityConsumer.objects.get_or_create(
                consumer=consumer,
                defaults={
                    'consumer_number': consumer_number,
                    'connection_type': 'RESIDENTIAL',
                    'sanctioned_load': 3.0,
                    'address': consumer.address
                }
            )
            
            # Create meter replacement request
            meter_req = MeterReplacementRequest.objects.create(
                consumer=elec_consumer,
                request_number=ref_number,
                reason=reason,
                current_meter_type='SINGLE_PHASE',  # Default
                requested_meter_type=meter_type,
                meter_price=meter_price_float,
                preferred_date=pref_date,
                preferred_time=preferred_time,
                additional_services=additional_services_list,
                installation_fee=installation_fee,
                total_cost=total_with_gst,
                status='PENDING'
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='Meter Replacement Request',
                message=f'Your meter replacement request {ref_number} has been submitted successfully.'
            )
            
            messages.success(request, f'Meter replacement request submitted successfully! Reference: {ref_number}')
            
        except Exception as e:
            logger.error(f"Error creating meter replacement: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'electricity-meter-replacement.html')
        
        return redirect('electricity-services')
    
    return render(request, 'electricity-meter-replacement.html')


@kiosk_login_required
def electricity_load_enhancement(request):
    """Load enhancement request"""
    consumer_id = request.session.get('consumer_id')
    
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
        
        # Generate reference number
        ref_number = f"LOAD{random.randint(100000, 999999)}"
        
        try:
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Get or create electricity consumer
            elec_consumer, created = ElectricityConsumer.objects.get_or_create(
                consumer=consumer,
                defaults={
                    'consumer_number': consumer_number,
                    'connection_type': 'RESIDENTIAL',
                    'sanctioned_load': 3.0,
                    'address': consumer.address
                }
            )
            
            # Create load enhancement request
            load_req = LoadEnhancementRequest.objects.create(
                consumer=elec_consumer,
                request_number=ref_number,
                current_load=current_load_float,
                requested_load=requested_load_float,
                reason=reason,
                reason_details=reason_details,
                status='PENDING',
                fee_amount=2500  # Default fee
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='Load Enhancement Request',
                message=f'Your load enhancement request {ref_number} has been submitted successfully.'
            )
            
            messages.success(request, f'Load enhancement request submitted successfully! Reference: {ref_number}')
            
        except Exception as e:
            logger.error(f"Error creating load enhancement: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'electricity-load-enhancement.html')
        
        return redirect('electricity-services')
    
    return render(request, 'electricity-load-enhancement.html')


@kiosk_login_required
def electricity_complaint(request):
    """Electricity complaint registration"""
    consumer_id = request.session.get('consumer_id')
    
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number', '123456789012'), 20)
        complaint_type = sanitize_input(request.POST.get('complaint_type'), 50)
        complaint_description = sanitize_input(request.POST.get('complaint_description'), 1000)
        
        # NEW FIELDS
        complaint_priority = sanitize_input(request.POST.get('complaint_priority', 'NORMAL'), 20)
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
        
        # Generate reference number
        ref_number = f"ELC{random.randint(100000, 999999)}"
        
        try:
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Create electricity consumer if not exists
            elec_consumer, created = ElectricityConsumer.objects.get_or_create(
                consumer=consumer,
                defaults={
                    'consumer_number': consumer_number_clean,
                    'connection_type': 'RESIDENTIAL',
                    'sanctioned_load': 3.0,
                    'address': consumer.address
                }
            )
            
            # Create complaint
            complaint = ElectricityComplaint.objects.create(
                consumer=elec_consumer,
                complaint_number=ref_number,
                complaint_type=complaint_type,
                priority=complaint_priority,
                description=complaint_description,
                contact_phone=contact_phone or consumer.mobile,
                status='PENDING'
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='COMPLAINT_UPDATE',
                title='Complaint Registered',
                message=f'Your complaint {ref_number} has been registered successfully.'
            )
            
            # Priority-based response message
            response_times = {
                'NORMAL': '24 hours',
                'URGENT': '4 hours',
                'EMERGENCY': '30 minutes'
            }
            response_time = response_times.get(complaint_priority, '24 hours')
            
            messages.success(request, f'Complaint registered successfully! Reference: {ref_number}. Expected response time: {response_time}')
            
        except Exception as e:
            logger.error(f"Error creating complaint: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'electricity-complaint.html')
        
        return redirect('electricity-services')
    
    return render(request, 'electricity-complaint.html')


# ================= WATER =================

@kiosk_login_required
def water_bill(request):
    """Water bill payment page"""
    consumer_id = request.session.get('consumer_id')
    
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
            
            # Create notification
            try:
                consumer = Consumer.objects.get(id=consumer_id)
                Notification.objects.create(
                    consumer=consumer,
                    notification_type='PAYMENT_SUCCESS',
                    title='Water Bill Paid',
                    message=f'Water bill payment of ₹{bill_amount} for consumer {consumer_no} successful. Transaction ID: {transaction_id}'
                )
            except:
                pass
            
            messages.success(request, f'Water bill payment of ₹{bill_amount} for consumer {consumer_no} successful! Transaction ID: {transaction_id}')
            return redirect('municipal-services')
        
        elif action == 'fetch':
            if not consumer_no:
                messages.error(request, 'Please enter consumer number')
                return render(request, 'water-bill.html')
            
            # Try to fetch from database
            try:
                water_consumer = WaterConsumer.objects.filter(consumer_number=consumer_no).first()
                if water_consumer:
                    # Get latest bill
                    latest_bill = WaterBill.objects.filter(consumer=water_consumer).order_by('-bill_date').first()
                    if latest_bill:
                        context = {
                            'show_bill': True,
                            'consumer_no': consumer_no,
                            'consumer_name': water_consumer.consumer.name,
                            'bill_number': latest_bill.bill_number,
                            'bill_date': latest_bill.bill_date.strftime('%d %b %Y'),
                            'due_date': latest_bill.due_date.strftime('%d %b %Y'),
                            'units_consumed': latest_bill.units_consumed,
                            'bill_amount': latest_bill.total_amount
                        }
                        return render(request, 'water-bill.html', context)
            except Exception as e:
                logger.error(f"Error fetching water bill: {e}")
            
            messages.error(request, 'Record not found. Please verify your details.')
            context['show_results'] = False
            bills = []
            data = []
    return render(request, 'water-bill.html')


# ================= MUNICIPAL SERVICES =================

@kiosk_login_required
def municipal_services(request):
    """Municipal services main menu"""
    consumer_id = request.session.get('consumer_id')
    
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        
        # Get pending applications count
        pending_count = 0
        pending_count += BuildingPlanApplication.objects.filter(consumer=consumer, status='PENDING').count()
        pending_count += Grievance.objects.filter(consumer=consumer, status='PENDING').count()
        pending_count += BirthCertificateApplication.objects.filter(consumer=consumer, status='PENDING').count()
        pending_count += DeathCertificateApplication.objects.filter(consumer=consumer, status='PENDING').count()
        
        context = {
            'pending_count': pending_count
        }
    except:
        context = {}
    
    return render(request, 'municipal-services.html', context)


@kiosk_login_required
def trade_license(request):
    """Trade license application"""
    consumer_id = request.session.get('consumer_id')
    
    if request.method == 'POST':
        business_name = sanitize_input(request.POST.get('business_name'), 100)
        business_type = sanitize_input(request.POST.get('business_type'), 50)
        owner_name = sanitize_input(request.POST.get('owner_name'), 100)
        address = sanitize_input(request.POST.get('address'), 500)
        gst_number = sanitize_input(request.POST.get('gst_number'), 15)
        
        if not all([business_name, business_type, owner_name, address]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'trade-license.html', {'form_data': request.POST})
        
        # Optional GST validation
        if gst_number and len(gst_number) != 15:
            messages.warning(request, 'GST number should be 15 characters if provided')
        
        # Generate reference number
        ref_number = f"TL{random.randint(100000, 999999)}"
        
        try:
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Create trade license application
            license = TradeLicense.objects.create(
                consumer=consumer,
                license_number=ref_number,
                business_name=business_name,
                business_type=business_type,
                owner_name=owner_name,
                address=address,
                gst_number=gst_number,
                issue_date=datetime.now().date(),
                expiry_date=datetime.now().date() + timedelta(days=365),
                license_fee=2500,
                status='ACTIVE'
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='Trade License Application',
                message=f'Your trade license application {ref_number} has been submitted successfully.'
            )
            
            messages.success(request, f'Trade license application submitted! Reference: {ref_number}')
            
        except Exception as e:
            logger.error(f"Error creating trade license: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'trade-license.html', {'form_data': request.POST})
        
        return redirect('municipal-services')
    
    context = {
        'application_fee': '500',
        'license_fee_range': '₹1,000 - ₹5,000*'
    }
    return render(request, 'trade-license.html', context)


@kiosk_login_required
def property_tax(request):
    """Property tax payment"""
    context = {}
    
    if request.method == 'POST':
        action = sanitize_input(request.POST.get('action'))
        property_id = sanitize_input(request.POST.get('property_id'), 20)
        
        if action == 'pay':
            tax_amount = sanitize_input(request.POST.get('tax_amount'))
            payment_method = sanitize_input(request.POST.get('payment_method', 'upi'), 10)
            
            if not property_id or not tax_amount:
                messages.error(request, 'Invalid tax details')
                return render(request, 'property-tax.html', context)
            
            # Generate transaction ID
            transaction_id = f"PTX{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
            
            # Create notification
            try:
                consumer_id = request.session.get('consumer_id')
                consumer = Consumer.objects.get(id=consumer_id)
                Notification.objects.create(
                    consumer=consumer,
                    notification_type='PAYMENT_SUCCESS',
                    title='Property Tax Paid',
                    message=f'Property tax of ₹{tax_amount} for property {property_id} paid successfully. Transaction ID: {transaction_id}'
                )
            except:
                pass
            
            messages.success(request, f'Property tax of ₹{tax_amount} for property {property_id} paid successfully! Transaction ID: {transaction_id}')
            return redirect('municipal-services')
        
        elif action == 'fetch':
            if not property_id:
                messages.error(request, 'Please enter property ID')
                return render(request, 'property-tax.html', context)
            
            # Try to fetch from database
            try:
                property_obj = Property.objects.filter(property_id=property_id).first()
                if property_obj:
                    tax = PropertyTax.objects.filter(property=property_obj).first()
                    if tax:
                        context['show_tax'] = True
                        context['tax_details'] = {
                            'property_id': property_obj.property_id,
                            'owner_name': property_obj.consumer.name,
                            'property_type': property_obj.property_type,
                            'area': property_obj.area_sqft,
                            'assessment_year': tax.assessment_year,
                            'due_date': tax.due_date.strftime('%d %b %Y'),
                            'amount': tax.tax_amount
                        }
                        return render(request, 'property-tax.html', context)
            except Exception as e:
                logger.error(f"Error fetching property tax: {e}")
            
            messages.error(request, 'Record not found. Please verify your details.')
            context['show_results'] = False
            bills = []
            data = []
    return render(request, 'property-tax.html')


@kiosk_login_required
def professional_tax(request):
    """Professional tax payment"""
    context = {}
    
    if request.method == 'POST':
        action = sanitize_input(request.POST.get('action'))
        ptin = sanitize_input(request.POST.get('ptin'), 20)
        
        if action == 'pay':
            tax_amount = sanitize_input(request.POST.get('tax_amount'))
            payment_method = sanitize_input(request.POST.get('payment_method', 'upi'), 10)
            
            if not ptin or not tax_amount:
                messages.error(request, 'Invalid tax details')
                return render(request, 'professional-tax.html', context)
            
            # Generate transaction ID
            transaction_id = f"PRF{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
            
            # Create notification
            try:
                consumer_id = request.session.get('consumer_id')
                consumer = Consumer.objects.get(id=consumer_id)
                Notification.objects.create(
                    consumer=consumer,
                    notification_type='PAYMENT_SUCCESS',
                    title='Professional Tax Paid',
                    message=f'Professional tax of ₹{tax_amount} for PTIN {ptin} paid successfully. Transaction ID: {transaction_id}'
                )
            except:
                pass
            
            messages.success(request, f'Professional tax of ₹{tax_amount} for PTIN {ptin} paid successfully! Transaction ID: {transaction_id}')
            return redirect('municipal-services')
        
        elif action == 'fetch':
            if not ptin:
                messages.error(request, 'Please enter PTIN')
                return render(request, 'professional-tax.html', context)
            
            # Try to fetch from database
            try:
                tax = ProfessionalTax.objects.filter(ptin=ptin).first()
                if tax:
                    context['show_tax'] = True
                    context['tax_details'] = {
                        'ptin': tax.ptin,
                        'name': tax.consumer.name,
                        'profession': tax.profession,
                        'assessment_year': tax.assessment_year,
                        'due_date': tax.due_date.strftime('%d %b %Y'),
                        'half_yearly_tax': tax.half_yearly_tax,
                        'penalty': tax.penalty,
                        'amount': tax.half_yearly_tax + tax.penalty
                    }
                    return render(request, 'professional-tax.html', context)
            except Exception as e:
                logger.error(f"Error fetching professional tax: {e}")
            
            messages.error(request, 'Record not found. Please verify your details.')
            context['show_results'] = False
            bills = []
            data = []
    return render(request, 'professional-tax.html')


@kiosk_login_required
def building_plan(request):
    """Building plan approval application"""
    consumer_id = request.session.get('consumer_id')
    
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
            return render(request, 'building-plan.html', {'form_data': request.POST})
        
        if not building_plan:
            messages.error(request, 'Please upload the building plan file')
            return render(request, 'building-plan.html', {'form_data': request.POST})
        
        # Validate file
        is_valid_ext, ext = validate_file_extension(building_plan.name, ['.pdf', '.dwg'])
        if not is_valid_ext:
            messages.error(request, 'Only PDF and DWG files are allowed')
            return render(request, 'building-plan.html', {'form_data': request.POST})
        
        is_valid_size, size = validate_file_size(building_plan, 25)
        if not is_valid_size:
            messages.error(request, 'File size exceeds 25MB limit')
            return render(request, 'building-plan.html', {'form_data': request.POST})
        
        # Validate plot area
        try:
            area = float(plot_area)
            if area <= 0:
                messages.error(request, 'Plot area must be positive')
                return render(request, 'building-plan.html', {'form_data': request.POST})
        except ValueError:
            messages.error(request, 'Please enter a valid plot area')
            return render(request, 'building-plan.html', {'form_data': request.POST})
        
        # Validate number of floors
        try:
            floors = int(num_floors)
            if floors < 1 or floors > 50:
                messages.error(request, 'Number of floors must be between 1 and 50')
                return render(request, 'building-plan.html', {'form_data': request.POST})
        except ValueError:
            messages.error(request, 'Please enter a valid number of floors')
            return render(request, 'building-plan.html', {'form_data': request.POST})
        
        # Generate reference number
        ref_number = f"BLD{random.randint(100000, 999999)}"
        
        try:
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Save the file
            # In production, you would save to media folder
            file_path = f"building_plans/{ref_number}_{building_plan.name}"
            
            # Create building plan application
            plan = BuildingPlanApplication.objects.create(
                consumer=consumer,
                application_number=ref_number,
                owner_name=owner_name,
                property_address=property_address,
                survey_number=survey_number,
                plot_area=area,
                building_type=building_type,
                num_floors=floors,
                building_plan_file=file_path,
                status='PENDING'
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='Building Plan Application',
                message=f'Your building plan application {ref_number} has been submitted successfully.'
            )
            
            messages.success(request, f'Building plan application submitted successfully! Reference: {ref_number}')
            
        except Exception as e:
            logger.error(f"Error creating building plan: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'building-plan.html', {'form_data': request.POST})
        
        return redirect('municipal-services')
    
    return render(request, 'building-plan.html')


# ================= GAS SERVICES - COMPLETELY FIXED =================

@kiosk_login_required
def gas_services(request):
    """Gas services main menu"""
    consumer_id = request.session.get('consumer_id')
    context = {}
    
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        # Check if user has gas connection
        try:
            gas_consumer = GasConsumer.objects.get(consumer=consumer)
            
            # Get pending applications count
            pending_bookings = GasCylinderBooking.objects.filter(consumer=gas_consumer, status='PENDING').count()
            pending_complaints = GasComplaint.objects.filter(consumer=gas_consumer, status='PENDING').count()
            
            context['user_consumer_info'] = f"{gas_consumer.consumer_number} - {gas_consumer.distributor}"
            context['has_connection'] = True
            context['pending_count'] = pending_bookings + pending_complaints
        except GasConsumer.DoesNotExist:
            context['has_connection'] = False
            context['pending_count'] = 0
    except:
        context['has_connection'] = False
        context['pending_count'] = 0
    
    return render(request, 'gas-services.html', context)


@kiosk_login_required
def gas_new_connection(request):
    """New gas connection application"""
    consumer_id = request.session.get('consumer_id')
    
    if request.method == 'POST':
        full_name = sanitize_input(request.POST.get('full_name'), 100)
        address = sanitize_input(request.POST.get('address'), 500)
        mobile = sanitize_input(request.POST.get('mobile'), 10)
        document_type = sanitize_input(request.POST.get('document_type'), 50)
        
        # Validate required fields
        if not all([full_name, address, mobile, document_type]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'gas-new-connection.html', {'form_data': request.POST})
        
        if not mobile.isdigit() or len(mobile) != 10:
            messages.error(request, 'Please enter a valid 10-digit mobile number')
            return render(request, 'gas-new-connection.html', {'form_data': request.POST})
        
        try:
            # Get the consumer
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Check if gas connection already exists
            if GasConsumer.objects.filter(consumer=consumer).exists():
                messages.error(request, 'You already have a gas connection. Please use existing connection for bookings.')
                return redirect('gas-services')
            
            # Generate unique consumer number
            consumer_number = f"GAS{random.randint(10000, 99999)}{random.randint(100, 999)}"
            
            # Create gas consumer record with CORRECT field names from model
            gas_consumer = GasConsumer.objects.create(
                consumer=consumer,
                consumer_number=consumer_number,
                distributor='HP Gas',
                distributor_code='HP' + str(random.randint(100, 999)),
                subsidy_status=True,
                subsidy_amount=200.00,
                total_cylinders_per_year=12,
                cylinders_remaining=12,
                address=address
            )
            
            # Create subsidy record for the consumer
            try:
                # Calculate next eligible date (30 days from now)
                next_eligible = datetime.now().date() + timedelta(days=30)
                
                GasSubsidy.objects.create(
                    consumer=gas_consumer,
                    is_active=True,
                    amount_per_cylinder=200.00,
                    total_cylinders_allotted=12,
                    cylinders_used=0,
                    next_eligible_date=next_eligible,
                    bank_account_number='',  # Will be updated later
                    bank_ifsc=''  # Will be updated later
                )
            except Exception as e:
                logger.error(f"Failed to create subsidy record: {e}")
            
            # Create notification
            try:
                Notification.objects.create(
                    consumer=consumer,
                    notification_type='APPLICATION_UPDATE',
                    title='Gas Connection Application Submitted',
                    message=f'Your gas connection application has been submitted. Your consumer number is {consumer_number}'
                )
            except Exception as e:
                logger.error(f"Failed to create notification: {e}")
            
            # Log the action
            try:
                AuditLog.objects.create(
                    consumer=consumer,
                    action='GAS_NEW_CONNECTION',
                    model_name='GasConsumer',
                    object_id=str(gas_consumer.id),
                    changes={'consumer_number': consumer_number, 'status': 'ACTIVE'},
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                )
            except Exception as e:
                logger.error(f"Failed to create audit log: {e}")
            
            messages.success(request, f'New gas connection application submitted! Your consumer number is {consumer_number}')
            return redirect('gas-services')
            
        except Consumer.DoesNotExist:
            messages.error(request, 'Consumer not found. Please login again.')
            return redirect('auth')
        except Exception as e:
            logger.error(f"Error creating gas connection: {e}")
            messages.error(request, f'An error occurred: {str(e)}. Please try again.')
            return render(request, 'gas-new-connection.html', {'form_data': request.POST})
    
    return render(request, 'gas-new-connection.html')


@kiosk_login_required
def gas_subsidy(request):
    """Gas subsidy status and information"""
    consumer_id = request.session.get('consumer_id')
    context = {}
    
    if request.method == 'POST':
        action = request.POST.get('action')
        consumer_no = sanitize_input(request.POST.get('consumer_no'), 20)
        
        if consumer_no:
            # Try to find gas consumer by consumer number
            try:
                gas_consumer = GasConsumer.objects.filter(consumer_number=consumer_no).first()
                
                if gas_consumer:
                    # Get subsidy information
                    try:
                        subsidy = GasSubsidy.objects.get(consumer=gas_consumer)
                        
                        # Calculate remaining cylinders
                        cylinders_used = subsidy.cylinders_used
                        total_cylinders = subsidy.total_cylinders_allotted
                        remaining = total_cylinders - cylinders_used
                        
                        # Get last booking if any
                        last_booking = GasCylinderBooking.objects.filter(
                            consumer=gas_consumer, 
                            status='DELIVERED'
                        ).order_by('-actual_delivery_date').first()
                        
                        context['show_subsidy'] = True
                        context['consumer_no'] = gas_consumer.consumer_number
                        context['subsidy'] = {
                            'status': 'Active' if subsidy.is_active else 'Inactive',
                            'amount_per_cylinder': str(subsidy.amount_per_cylinder),
                            'total_cylinders': str(total_cylinders),
                            'remaining_cylinders': str(remaining),
                            'next_eligibility': subsidy.next_eligible_date.strftime('%d %b %Y'),
                            'bank_account': f"XXXXXX{subsidy.bank_account_number[-4:]}" if subsidy.bank_account_number else 'Not available',
                            'last_transaction': {
                                'amount': str(last_booking.cylinder_price),
                                'date': last_booking.actual_delivery_date.strftime('%d %b %Y')
                            } if last_booking else None
                        }
                        
                    except GasSubsidy.DoesNotExist:
                        # Consumer exists but no subsidy record
                        context['show_subsidy'] = True
                        context['consumer_no'] = gas_consumer.consumer_number
                        context['subsidy'] = {
                            'status': 'Not Enrolled',
                            'amount_per_cylinder': '0',
                            'total_cylinders': '0',
                            'remaining_cylinders': '0',
                            'next_eligibility': 'N/A',
                            'bank_account': 'Not available',
                            'last_transaction': None
                        }
                else:
                    # No gas consumer found - show sample data for demo
                    context['show_subsidy'] = True
                    context['consumer_no'] = consumer_no
                    context['subsidy'] = {
                        'status': 'Active' if random.choice([True, False]) else 'Inactive',
                        'amount_per_cylinder': '200',
                        'total_cylinders': '12',
                        'remaining_cylinders': str(random.randint(0, 12)),
                        'next_eligibility': (datetime.now().date() + timedelta(days=30)).strftime('%d %b %Y'),
                        'bank_account': 'XXXXXX1234',
                        'last_transaction': {
                            'amount': '856',
                            'date': (datetime.now().date() - timedelta(days=random.randint(5, 20))).strftime('%d %b %Y')
                        }
                    }
            except Exception as e:
                logger.error(f"Error fetching gas subsidy: {e}")
                messages.error(request, 'Error fetching subsidy information. Please try again.')
    
    context['last_updated'] = datetime.now().strftime('%d %b %Y')
    return render(request, 'gas-subsidy.html', context)


@kiosk_login_required
def gas_cylinder_booking(request):
    """Gas cylinder booking"""
    consumer_id = request.session.get('consumer_id')
    context = {}
    
    # Get consumer's gas connection if exists
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        gas_consumer = GasConsumer.objects.filter(consumer=consumer).first()
        
        if gas_consumer:
            # Get subsidy information
            try:
                subsidy = GasSubsidy.objects.get(consumer=gas_consumer)
                remaining_subsidies = subsidy.total_cylinders_allotted - subsidy.cylinders_used
            except GasSubsidy.DoesNotExist:
                remaining_subsidies = gas_consumer.cylinders_remaining
            
            context['consumer'] = {
                'consumer_no': gas_consumer.consumer_number,
                'subsidy_active': gas_consumer.subsidy_status,
                'remaining_subsidies': remaining_subsidies
            }
        else:
            # No gas connection found
            context['consumer'] = {
                'consumer_no': 'Not Available',
                'subsidy_active': False,
                'remaining_subsidies': 0
            }
            messages.warning(request, 'No gas connection found. Please apply for new connection first.')
    except Exception as e:
        logger.error(f"Error getting gas consumer: {e}")
        context['consumer'] = {
            'consumer_no': '1234 5678 9012',
            'subsidy_active': True,
            'remaining_subsidies': 8
        }
    
    # Define cylinder types with correct enum values matching the model
    context['cylinders'] = [
        {'type': '14.2KG_DOMESTIC', 'name': '14.2 kg Domestic', 'price': 856.00, 'subsidized': True, 'selected': True},
        {'type': '5KG_DOMESTIC', 'name': '5 kg Domestic', 'price': 425.00, 'subsidized': False, 'selected': False},
        {'type': '19KG_COMMERCIAL', 'name': '19 kg Commercial', 'price': 1850.00, 'subsidized': False, 'selected': False},
    ]
    
    if request.method == 'POST':
        cylinder_type = sanitize_input(request.POST.get('cylinder_type'), 20)
        cylinder_price = request.POST.get('cylinder_price_hidden')
        
        if not cylinder_type:
            messages.error(request, 'Please select a cylinder type')
            return render(request, 'gas-cylinder-booking.html', context)
        
        try:
            # Get the consumer
            consumer = Consumer.objects.get(id=consumer_id)
            gas_consumer = GasConsumer.objects.filter(consumer=consumer).first()
            
            if not gas_consumer:
                messages.error(request, 'No gas connection found. Please apply for new connection first.')
                return redirect('gas-new-connection')
            
            # Check subsidy availability
            if cylinder_type == '14.2KG_DOMESTIC':
                try:
                    subsidy = GasSubsidy.objects.get(consumer=gas_consumer)
                    if subsidy.cylinders_used >= subsidy.total_cylinders_allotted:
                        messages.error(request, 'No subsidized cylinders remaining. Please try commercial cylinder.')
                        return render(request, 'gas-cylinder-booking.html', context)
                except GasSubsidy.DoesNotExist:
                    if gas_consumer.cylinders_remaining <= 0:
                        messages.error(request, 'No subsidized cylinders remaining. Please try commercial cylinder.')
                        return render(request, 'gas-cylinder-booking.html', context)
            
            # Generate booking number
            booking_number = f"BOOK{random.randint(10000, 99999)}{random.randint(100, 999)}"
            
            # Calculate expected delivery date (2-3 days from now)
            expected_delivery = datetime.now().date() + timedelta(days=random.randint(2, 3))
            
            # Create booking
            booking = GasCylinderBooking.objects.create(
                consumer=gas_consumer,
                booking_number=booking_number,
                cylinder_type=cylinder_type,
                cylinder_price=cylinder_price,
                status='PENDING',
                expected_delivery_date=expected_delivery
            )
            
            # Update remaining cylinders for subsidized booking
            if cylinder_type == '14.2KG_DOMESTIC':
                try:
                    subsidy = GasSubsidy.objects.get(consumer=gas_consumer)
                    subsidy.cylinders_used += 1
                    subsidy.save()
                    
                    # Update next eligible date (30 days from now)
                    subsidy.next_eligible_date = datetime.now().date() + timedelta(days=30)
                    subsidy.save()
                except GasSubsidy.DoesNotExist:
                    gas_consumer.cylinders_remaining -= 1
                    gas_consumer.save()
            
            # Create notification
            try:
                Notification.objects.create(
                    consumer=consumer,
                    notification_type='APPLICATION_UPDATE',
                    title='Cylinder Booked',
                    message=f'Your cylinder has been booked. Booking number: {booking_number}'
                )
            except Exception as e:
                logger.error(f"Failed to create notification: {e}")
            
            # Log the action
            try:
                AuditLog.objects.create(
                    consumer=consumer,
                    action='CYLINDER_BOOKING',
                    model_name='GasCylinderBooking',
                    object_id=str(booking.id),
                    changes={'booking_number': booking_number, 'type': cylinder_type},
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                )
            except Exception as e:
                logger.error(f"Failed to create audit log: {e}")
            
            messages.success(request, f'Cylinder booked successfully! Reference: {booking_number}')
            return redirect('gas-services')
            
        except Consumer.DoesNotExist:
            messages.error(request, 'Consumer not found. Please login again.')
            return redirect('auth')
        except Exception as e:
            logger.error(f"Error booking cylinder: {e}")
            messages.error(request, 'An error occurred. Please try again.')
    
    return render(request, 'gas-cylinder-booking.html', context)


@kiosk_login_required
def gas_consumer_lookup(request):
    """Gas consumer lookup by Aadhaar"""
    context = {}
    
    if request.method == 'POST':
        aadhaar_number = sanitize_input(request.POST.get('aadhaar_number'), 12)
        
        if not aadhaar_number or len(aadhaar_number) != 12:
            messages.error(request, 'Please enter a valid 12-digit Aadhaar number')
            return render(request, 'gas-consumer-lookup.html', context)
        
        # Simple Aadhaar validation
        if not aadhaar_number.isdigit():
            messages.error(request, 'Aadhaar must contain only digits')
            return render(request, 'gas-consumer-lookup.html', context)
        
        try:
            # Try to find consumer by Aadhaar
            consumer = Consumer.objects.filter(aadhaar_number=aadhaar_number).first()
            
            if consumer:
                # Try to find gas consumer
                gas_consumer = GasConsumer.objects.filter(consumer=consumer).first()
                
                if gas_consumer:
                    # Get last booking
                    last_booking = GasCylinderBooking.objects.filter(
                        consumer=gas_consumer
                    ).order_by('-booking_date').first()
                    
                    context['show_result'] = True
                    context['consumer'] = {
                        'consumer_no': ' '.join([gas_consumer.consumer_number[i:i+4] for i in range(0, len(gas_consumer.consumer_number), 4)]),
                        'name': consumer.name,
                        'address': consumer.address,
                        'distributor': gas_consumer.distributor,
                        'status': 'Active' if gas_consumer.subsidy_status else 'Inactive',
                        'last_booking': last_booking.booking_date.strftime('%d %b %Y') if last_booking else 'No bookings yet'
                    }
                else:
                    # Consumer exists but no gas connection
                    context['show_result'] = True
                    context['consumer'] = {
                        'consumer_no': 'No gas connection',
                        'name': consumer.name,
                        'address': consumer.address,
                        'distributor': 'Not registered',
                        'status': 'No Connection',
                        'last_booking': 'N/A'
                    }
            else:
                # No consumer found - use sample data
                context['show_result'] = True
                context['consumer'] = {
                    'consumer_no': '1234 5678 9012',
                    'name': 'Rajesh Kumar',
                    'address': '123, Gandhi Nagar',
                    'distributor': 'HP Gas - Indane',
                    'status': 'Active',
                    'last_booking': '15 Feb 2026'
                }
                
        except Exception as e:
            logger.error(f"Error in consumer lookup: {e}")
            messages.error(request, 'An error occurred. Please try again.')
    
    return render(request, 'gas-consumer-lookup.html', context)


@kiosk_login_required
def gas_complaint(request):
    """Gas complaint registration"""
    consumer_id = request.session.get('consumer_id')
    context = {}
    
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number', '123456789012'), 20)
        complaint_type = sanitize_input(request.POST.get('complaint_type'), 50)
        description = sanitize_input(request.POST.get('description'), 1000)
        
        if not complaint_type:
            messages.error(request, 'Please select a complaint type')
            return render(request, 'gas-complaint.html', context)
        
        if not description or description.strip() == '':
            messages.error(request, 'Please describe your complaint')
            return render(request, 'gas-complaint.html', context)
        
        if len(description.strip()) < 10:
            messages.error(request, 'Please provide a more detailed description (minimum 10 characters)')
            return render(request, 'gas-complaint.html', context)
        
        try:
            # Get the consumer
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Try to find gas consumer
            gas_consumer = GasConsumer.objects.filter(consumer=consumer).first()
            
            if not gas_consumer:
                messages.error(request, 'No gas connection found. Please apply for new connection first.')
                return redirect('gas-new-connection')
            
            # Generate complaint number
            complaint_number = f"GASCMP{random.randint(10000, 99999)}"
            
            # Create complaint
            complaint = GasComplaint.objects.create(
                consumer=gas_consumer,
                complaint_number=complaint_number,
                complaint_type=complaint_type,
                description=description,
                status='PENDING'
            )
            
            # Create notification
            try:
                Notification.objects.create(
                    consumer=consumer,
                    notification_type='COMPLAINT_UPDATE',
                    title='Complaint Registered',
                    message=f'Your complaint {complaint_number} has been registered successfully.'
                )
            except Exception as e:
                logger.error(f"Failed to create notification: {e}")
            
            # Log the action
            try:
                AuditLog.objects.create(
                    consumer=consumer,
                    action='GAS_COMPLAINT',
                    model_name='GasComplaint',
                    object_id=str(complaint.id),
                    changes={'complaint_number': complaint_number, 'type': complaint_type},
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                )
            except Exception as e:
                logger.error(f"Failed to create audit log: {e}")
            
            messages.success(request, f'Complaint registered successfully! Reference: {complaint_number}')
            return redirect('gas-services')
            
        except Consumer.DoesNotExist:
            messages.error(request, 'Consumer not found. Please login again.')
            return redirect('auth')
        except Exception as e:
            logger.error(f"Error registering complaint: {e}")
            messages.error(request, 'An error occurred. Please try again.')
    
    return render(request, 'gas-complaint.html', context)


@kiosk_login_required
def gas_bookings_status(request):
    """Gas booking status tracking"""
    context = {}
    
    if request.method == 'POST':
        reference_number = sanitize_input(request.POST.get('reference_number'), 20)
        
        if not reference_number:
            messages.error(request, 'Please enter a reference number')
            return render(request, 'gas-booking-status.html', context)
        
        # Try to find in database first
        try:
            booking = GasCylinderBooking.objects.filter(booking_number=reference_number).first()
            if booking:
                status_map = {
                    'PENDING': 'pending',
                    'PROCESSED': 'processed',
                    'OUT_FOR_DELIVERY': 'out_for_delivery',
                    'DELIVERED': 'delivered',
                    'CANCELLED': 'cancelled'
                }
                
                # Get delivery person info
                delivery_info = ''
                if booking.delivery_person:
                    delivery_info = f"{booking.delivery_person}"
                    if booking.delivery_person_phone:
                        delivery_info += f" ({booking.delivery_person_phone})"
                
                # Get consumer name
                consumer_name = booking.consumer.consumer.name if booking.consumer and booking.consumer.consumer else 'Customer'
                
                context['booking'] = {
                    'reference_number': booking.booking_number,
                    'consumer_name': consumer_name,
                    'booked_date': booking.booking_date.strftime('%d %b %Y, %I:%M %p'),
                    'expected_delivery': booking.expected_delivery_date.strftime('%d %b %Y') if booking.expected_delivery_date else 'Not scheduled',
                    'actual_delivery': booking.actual_delivery_date.strftime('%d %b %Y, %I:%M %p') if booking.actual_delivery_date else None,
                    'delivery_person': delivery_info or 'To be assigned',
                    'cylinder_type': booking.get_cylinder_type_display(),
                    'status': status_map.get(booking.status, 'pending')
                }
                return render(request, 'gas-booking-status.html', context)
        except Exception as e:
            logger.error(f"Error fetching booking: {e}")
        
        messages.error(request, 'Record not found. Please verify your details.')
        context['show_results'] = False
        bills = []
        data = []
    return render(request, 'gas-booking-status.html', context)


@kiosk_login_required
def gas_bill_payment(request):
    """Gas bill payment"""
    consumer_id = request.session.get('consumer_id')
    
    if request.method == 'POST':
        consumer_number = sanitize_input(request.POST.get('consumer_number'), 20)
        amount = sanitize_input(request.POST.get('amount'))
        payment_method = sanitize_input(request.POST.get('payment_method', 'upi'), 10)
        card_number = sanitize_input(request.POST.get('card_number'), 19)
        cvv = sanitize_input(request.POST.get('cvv'), 3)
        pin = sanitize_input(request.POST.get('pin'), 4)
        
        if not consumer_number or not amount:
            messages.error(request, 'Invalid payment details')
            return render(request, 'gas-bill-payment.html')
        
        # Validate amount
        try:
            amount_value = float(amount)
            if amount_value <= 0:
                messages.error(request, 'Invalid amount')
                return render(request, 'gas-bill-payment.html')
        except ValueError:
            messages.error(request, 'Invalid amount')
            return render(request, 'gas-bill-payment.html')
        
        # Validate card details if ATM payment
        if payment_method == 'atm':
            card_clean = card_number.replace(' ', '')
            if len(card_clean) < 15 or not card_clean.isdigit():
                messages.error(request, 'Please enter a valid card number')
                return render(request, 'gas-bill-payment.html')
            if len(cvv) != 3 or not cvv.isdigit():
                messages.error(request, 'Please enter a valid CVV')
                return render(request, 'gas-bill-payment.html')
            if len(pin) != 4 or not pin.isdigit():
                messages.error(request, 'Please enter a valid PIN')
                return render(request, 'gas-bill-payment.html')
        
        # Generate transaction ID
        transaction_id = f"GAS{datetime.now().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"
        
        try:
            # Get the consumer
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Log payment
            try:
                AuditLog.objects.create(
                    consumer=consumer,
                    action='GAS_PAYMENT',
                    model_name='Payment',
                    object_id='',
                    changes={'amount': amount, 'transaction': transaction_id, 'method': payment_method},
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                )
            except Exception as e:
                logger.error(f"Failed to create audit log: {e}")
            
            # Create notification
            try:
                Notification.objects.create(
                    consumer=consumer,
                    notification_type='PAYMENT_SUCCESS',
                    title='Payment Successful',
                    message=f'Your gas bill payment of ₹{amount} was successful. Transaction ID: {transaction_id}'
                )
            except Exception as e:
                logger.error(f"Failed to create notification: {e}")
                
        except Exception as e:
            logger.error(f"Error processing payment: {e}")
        
        messages.success(request, f'Gas bill payment of ₹{amount} successful! Transaction ID: {transaction_id}')
        return redirect('gas-services')
    
    return render(request, 'gas-bill-payment.html')


# ================= GRIEVANCE =================

@kiosk_login_required
def grievance(request):
    """General grievance registration"""
    consumer_id = request.session.get('consumer_id')
    
    if request.method == 'POST':
        name = sanitize_input(request.POST.get('name'), 100)
        mobile = sanitize_input(request.POST.get('mobile'), 10)
        location = sanitize_input(request.POST.get('location'), 200)
        description = sanitize_input(request.POST.get('description'), 1000)
        department = sanitize_input(request.POST.get('department'), 50)
        
        # Validate required fields
        if not all([name, mobile, location, description, department]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'grievance.html', {'form_data': request.POST})
        
        if not mobile.isdigit() or len(mobile) != 10:
            messages.error(request, 'Please enter a valid 10-digit mobile number')
            return render(request, 'grievance.html', {'form_data': request.POST})
        
        # Validate description length
        if len(description.strip()) < 10:
            messages.error(request, 'Please provide a more detailed description (minimum 10 characters)')
            return render(request, 'grievance.html', {'form_data': request.POST})
        
        try:
            # Get the consumer
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Generate grievance number
            grievance_number = f"GRV{random.randint(10000, 99999)}"
            
            # Create grievance
            grievance = Grievance.objects.create(
                consumer=consumer,
                grievance_number=grievance_number,
                department=department,
                name=name,
                mobile=mobile,
                location=location,
                description=description,
                status='PENDING'
            )
            
            # Create notification
            try:
                Notification.objects.create(
                    consumer=consumer,
                    notification_type='APPLICATION_UPDATE',
                    title='Grievance Registered',
                    message=f'Your grievance has been registered. Reference number: {grievance_number}'
                )
            except Exception as e:
                logger.error(f"Failed to create notification: {e}")
            
            # Log the action
            try:
                AuditLog.objects.create(
                    consumer=consumer,
                    action='GRIEVANCE_SUBMITTED',
                    model_name='Grievance',
                    object_id=str(grievance.id),
                    changes={'grievance_number': grievance_number, 'department': department},
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                )
            except Exception as e:
                logger.error(f"Failed to create audit log: {e}")
            
            messages.success(request, f'Grievance registered successfully! Reference: {grievance_number}')
            return redirect('municipal-services')
            
        except Consumer.DoesNotExist:
            messages.error(request, 'Consumer not found. Please login again.')
            return redirect('auth')
        except Exception as e:
            logger.error(f"Error registering grievance: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'grievance.html', {'form_data': request.POST})
    
    return render(request, 'grievance.html')


# ================= BIRTH CERTIFICATE =================

@kiosk_login_required
def birth_certificate(request):
    """Birth certificate application"""
    consumer_id = request.session.get('consumer_id')
    
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
            return render(request, 'birth-certificate.html', {'form_data': request.POST})
        
        # Validate date of birth (not in future)
        from datetime import date
        try:
            birth_date = date.fromisoformat(dob)
            if birth_date > date.today():
                messages.error(request, 'Date of birth cannot be in the future')
                return render(request, 'birth-certificate.html', {'form_data': request.POST})
        except ValueError:
            messages.error(request, 'Invalid date format')
            return render(request, 'birth-certificate.html', {'form_data': request.POST})
        
        try:
            # Get the consumer
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Generate reference number
            ref_number = f"BRTH{random.randint(100000, 999999)}"
            
            # Create birth certificate application
            birth_cert = BirthCertificateApplication.objects.create(
                consumer=consumer,
                application_number=ref_number,
                child_name=child_name,
                date_of_birth=birth_date,
                gender=gender,
                place_of_birth=birth_place,
                father_name=father_name,
                mother_name=mother_name,
                permanent_address=permanent_address,
                status='PENDING'
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='Birth Certificate Application',
                message=f'Your birth certificate application {ref_number} has been submitted successfully.'
            )
            
            messages.success(request, f'Birth certificate application submitted successfully! Reference: {ref_number}')
            
        except Exception as e:
            logger.error(f"Error creating birth certificate: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'birth-certificate.html', {'form_data': request.POST})
        
        return redirect('municipal-services')
    
    return render(request, 'birth-certificate.html')


# ================= DEATH CERTIFICATE =================

@kiosk_login_required
def death_certificate(request):
    """Death certificate application"""
    consumer_id = request.session.get('consumer_id')
    
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
            return render(request, 'death-certificate.html', {'form_data': request.POST})
        
        from datetime import date
        if date_of_death:
            try:
                death_date = date.fromisoformat(date_of_death)
                if death_date > date.today():
                    messages.error(request, 'Date of death cannot be in the future')
                    return render(request, 'death-certificate.html', {'form_data': request.POST})
            except ValueError:
                messages.error(request, 'Invalid date format')
                return render(request, 'death-certificate.html', {'form_data': request.POST})
        
        try:
            # Get the consumer
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Generate reference number
            ref_number = f"DTH{random.randint(100000, 999999)}"
            
            # Create death certificate application
            death_cert = DeathCertificateApplication.objects.create(
                consumer=consumer,
                application_number=ref_number,
                deceased_name=deceased_name,
                date_of_death=death_date,
                place_of_death=place_of_death,
                gender=gender,
                father_name=father_name,
                mother_name=mother_name,
                permanent_address=permanent_address,
                cause_of_death=cause_of_death,
                status='PENDING'
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='Death Certificate Application',
                message=f'Your death certificate application {ref_number} has been submitted successfully.'
            )
            
            messages.success(request, f'Death certificate application submitted successfully! Reference: {ref_number}')
            
        except Exception as e:
            logger.error(f"Error creating death certificate: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'death-certificate.html', {'form_data': request.POST})
        
        return redirect('municipal-services')
    
    return render(request, 'death-certificate.html')


# ================= MARRIAGE REGISTRATION =================

@kiosk_login_required
def marriage_registration(request):
    """Marriage registration application"""
    consumer_id = request.session.get('consumer_id')
    
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
            return render(request, 'marriage-registration.html', {'form_data': request.POST})
        
        # Validate marriage date (not in future)
        from datetime import date
        try:
            mar_date = date.fromisoformat(marriage_date)
            if mar_date > date.today():
                messages.error(request, 'Marriage date cannot be in the future')
                return render(request, 'marriage-registration.html', {'form_data': request.POST})
        except ValueError:
            messages.error(request, 'Invalid marriage date format')
            return render(request, 'marriage-registration.html', {'form_data': request.POST})
        
        # Validate Aadhaar if provided
        if groom_aadhaar and (len(groom_aadhaar) != 12 or not groom_aadhaar.isdigit()):
            messages.error(request, 'Please enter a valid 12-digit Aadhaar for groom')
            return render(request, 'marriage-registration.html', {'form_data': request.POST})
        
        if bride_aadhaar and (len(bride_aadhaar) != 12 or not bride_aadhaar.isdigit()):
            messages.error(request, 'Please enter a valid 12-digit Aadhaar for bride')
            return render(request, 'marriage-registration.html', {'form_data': request.POST})
        
        try:
            # Get the consumer
            consumer = Consumer.objects.get(id=consumer_id)
            
            # Generate reference number
            ref_number = f"MAR{random.randint(100000, 999999)}"
            
            # Create marriage registration
            marriage = MarriageRegistration.objects.create(
                application_number=ref_number,
                groom_name=groom_name,
                groom_dob=datetime.strptime(groom_dob, '%Y-%m-%d').date() if groom_dob else None,
                groom_aadhaar=groom_aadhaar,
                groom_father_name=groom_father_name,
                bride_name=bride_name,
                bride_dob=datetime.strptime(bride_dob, '%Y-%m-%d').date() if bride_dob else None,
                bride_aadhaar=bride_aadhaar,
                bride_father_name=bride_father_name,
                marriage_date=mar_date,
                marriage_place=marriage_place,
                marriage_type=marriage_type,
                witness1_name=witness1_name,
                witness2_name=witness2_name,
                status='PENDING'
            )
            
            # Create notification
            Notification.objects.create(
                consumer=consumer,
                notification_type='APPLICATION_UPDATE',
                title='Marriage Registration',
                message=f'Your marriage registration application {ref_number} has been submitted successfully.'
            )
            
            messages.success(request, f'Marriage registration submitted successfully! Reference: {ref_number}')
            
        except Exception as e:
            logger.error(f"Error creating marriage registration: {e}")
            messages.error(request, 'An error occurred. Please try again.')
            return render(request, 'marriage-registration.html', {'form_data': request.POST})
        
        return redirect('municipal-services')
    
    return render(request, 'marriage-registration.html')


# ================= APPLICATION STATUS - COMPLETELY FIXED =================

@kiosk_login_required
def application_status(request):
    """Application and complaint status - FIXED to show all records"""
    context = {}
    consumer_id = request.session.get('consumer_id')
    
    # Get all applications and complaints for this consumer
    all_applications = []
    
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        
        # ===== ELECTRICITY APPLICATIONS =====
        try:
            elec_consumer = ElectricityConsumer.objects.filter(consumer=consumer).first()
            if elec_consumer:
                # Electricity Bills
                for bill in ElectricityBill.objects.filter(consumer=elec_consumer).order_by('-bill_date')[:10]:
                    all_applications.append({
                        'type': 'Bill',
                        'reference': bill.bill_number,
                        'department': 'Electricity',
                        'submitted_date': bill.bill_date,
                        'status': bill.status,
                        'details': f'Amount: ₹{bill.total_amount}, Units: {bill.units_consumed}',
                        'model': 'ElectricityBill',
                        'id': bill.id
                    })
                
                # Electricity Complaints
                for complaint in ElectricityComplaint.objects.filter(consumer=elec_consumer).order_by('-created_at'):
                    all_applications.append({
                        'type': 'Complaint',
                        'reference': complaint.complaint_number,
                        'department': 'Electricity',
                        'submitted_date': complaint.created_at.date(),
                        'status': complaint.status,
                        'details': f'Type: {complaint.complaint_type}, Priority: {complaint.priority}',
                        'model': 'ElectricityComplaint',
                        'id': complaint.id
                    })
                
                # Load Enhancement Requests
                for req in LoadEnhancementRequest.objects.filter(consumer=elec_consumer).order_by('-created_at'):
                    all_applications.append({
                        'type': 'Load Enhancement',
                        'reference': req.request_number,
                        'department': 'Electricity',
                        'submitted_date': req.created_at.date(),
                        'status': req.status,
                        'details': f'{req.current_load}kW → {req.requested_load}kW',
                        'model': 'LoadEnhancementRequest',
                        'id': req.id
                    })
                
                # Meter Replacement Requests
                for req in MeterReplacementRequest.objects.filter(consumer=elec_consumer).order_by('-created_at'):
                    all_applications.append({
                        'type': 'Meter Replacement',
                        'reference': req.request_number,
                        'department': 'Electricity',
                        'submitted_date': req.created_at.date(),
                        'status': req.status,
                        'details': f'New Meter: {req.requested_meter_type}',
                        'model': 'MeterReplacementRequest',
                        'id': req.id
                    })
                
                # Name Transfer Requests
                for req in NameTransferRequest.objects.filter(consumer=elec_consumer).order_by('-created_at'):
                    all_applications.append({
                        'type': 'Name Transfer',
                        'reference': req.request_number,
                        'department': 'Electricity',
                        'submitted_date': req.created_at.date(),
                        'status': req.status,
                        'details': f'New Owner: {req.new_owner_name}',
                        'model': 'NameTransferRequest',
                        'id': req.id
                    })
        except Exception as e:
            logger.error(f"Error fetching electricity applications: {e}")
        
        # ===== GAS APPLICATIONS =====
        try:
            gas_consumer = GasConsumer.objects.filter(consumer=consumer).first()
            if gas_consumer:
                # Gas Cylinder Bookings
                for booking in GasCylinderBooking.objects.filter(consumer=gas_consumer).order_by('-created_at'):
                    all_applications.append({
                        'type': 'Cylinder Booking',
                        'reference': booking.booking_number,
                        'department': 'Gas',
                        'submitted_date': booking.created_at.date(),
                        'status': booking.status,
                        'details': f'Type: {booking.get_cylinder_type_display()}, Price: ₹{booking.cylinder_price}',
                        'model': 'GasCylinderBooking',
                        'id': booking.id
                    })
                
                # Gas Complaints
                for complaint in GasComplaint.objects.filter(consumer=gas_consumer).order_by('-created_at'):
                    all_applications.append({
                        'type': 'Complaint',
                        'reference': complaint.complaint_number,
                        'department': 'Gas',
                        'submitted_date': complaint.created_at.date(),
                        'status': complaint.status,
                        'details': f'Type: {complaint.complaint_type}',
                        'model': 'GasComplaint',
                        'id': complaint.id
                    })
        except Exception as e:
            logger.error(f"Error fetching gas applications: {e}")
        
        # ===== WATER APPLICATIONS =====
        try:
            water_consumer = WaterConsumer.objects.filter(consumer=consumer).first()
            if water_consumer:
                # Water Bills
                for bill in WaterBill.objects.filter(consumer=water_consumer).order_by('-bill_date')[:10]:
                    all_applications.append({
                        'type': 'Bill',
                        'reference': bill.bill_number,
                        'department': 'Water',
                        'submitted_date': bill.bill_date,
                        'status': bill.status,
                        'details': f'Amount: ₹{bill.total_amount}, Units: {bill.units_consumed}',
                        'model': 'WaterBill',
                        'id': bill.id
                    })
        except Exception as e:
            logger.error(f"Error fetching water applications: {e}")
        
        # ===== MUNICIPAL APPLICATIONS =====
        try:
            # Building Plan Applications
            for plan in BuildingPlanApplication.objects.filter(consumer=consumer).order_by('-created_at'):
                all_applications.append({
                    'type': 'Building Plan',
                    'reference': plan.application_number,
                    'department': 'Municipal',
                    'submitted_date': plan.created_at.date(),
                    'status': plan.status,
                    'details': f'Type: {plan.building_type}, Floors: {plan.num_floors}',
                    'model': 'BuildingPlanApplication',
                    'id': plan.id
                })
            
            # Grievances
            for grievance in Grievance.objects.filter(consumer=consumer).order_by('-created_at'):
                all_applications.append({
                    'type': 'Grievance',
                    'reference': grievance.grievance_number,
                    'department': grievance.department,
                    'submitted_date': grievance.created_at.date(),
                    'status': grievance.status,
                    'details': f'Department: {grievance.department}',
                    'model': 'Grievance',
                    'id': grievance.id
                })
            
            # Birth Certificates
            for cert in BirthCertificateApplication.objects.filter(consumer=consumer).order_by('-created_at'):
                all_applications.append({
                    'type': 'Birth Certificate',
                    'reference': cert.application_number,
                    'department': 'Municipal',
                    'submitted_date': cert.created_at.date(),
                    'status': cert.status,
                    'details': f'Child: {cert.child_name}',
                    'model': 'BirthCertificateApplication',
                    'id': cert.id
                })
            
            # Death Certificates
            for cert in DeathCertificateApplication.objects.filter(consumer=consumer).order_by('-created_at'):
                all_applications.append({
                    'type': 'Death Certificate',
                    'reference': cert.application_number,
                    'department': 'Municipal',
                    'submitted_date': cert.created_at.date(),
                    'status': cert.status,
                    'details': f'Deceased: {cert.deceased_name}',
                    'model': 'DeathCertificateApplication',
                    'id': cert.id
                })
            
            # Trade Licenses
            for license in TradeLicense.objects.filter(consumer=consumer).order_by('-created_at'):
                all_applications.append({
                    'type': 'Trade License',
                    'reference': license.license_number,
                    'department': 'Municipal',
                    'submitted_date': license.issue_date,
                    'status': license.status,
                    'details': f'Business: {license.business_name}',
                    'model': 'TradeLicense',
                    'id': license.id
                })
            
            # Property Tax
            for property in Property.objects.filter(consumer=consumer):
                for tax in PropertyTax.objects.filter(property=property).order_by('-created_at'):
                    all_applications.append({
                        'type': 'Property Tax',
                        'reference': tax.tax_id,
                        'department': 'Municipal',
                        'submitted_date': tax.created_at.date(),
                        'status': tax.status,
                        'details': f'Amount: ₹{tax.tax_amount}, Year: {tax.assessment_year}',
                        'model': 'PropertyTax',
                        'id': tax.id
                    })
            
            # Professional Tax
            for tax in ProfessionalTax.objects.filter(consumer=consumer).order_by('-created_at'):
                all_applications.append({
                    'type': 'Professional Tax',
                    'reference': tax.ptin,
                    'department': 'Municipal',
                    'submitted_date': tax.created_at.date(),
                    'status': tax.status,
                    'details': f'Amount: ₹{tax.half_yearly_tax}, Year: {tax.assessment_year}',
                    'model': 'ProfessionalTax',
                    'id': tax.id
                })
        except Exception as e:
            logger.error(f"Error fetching municipal applications: {e}")
        
        # Sort by date (most recent first)
        all_applications.sort(key=lambda x: x['submitted_date'], reverse=True)
        
        context['all_applications'] = all_applications
        context['total_count'] = len(all_applications)
        
        # Count by status
        context['pending_count'] = sum(1 for app in all_applications if app['status'] in ['PENDING', 'pending'])
        context['approved_count'] = sum(1 for app in all_applications if app['status'] in ['APPROVED', 'PAID', 'SUCCESS', 'ACTIVE'])
        context['resolved_count'] = sum(1 for app in all_applications if app['status'] in ['RESOLVED', 'COMPLETED', 'DELIVERED', 'ISSUED'])
        
    except Exception as e:
        logger.error(f"Error fetching applications: {e}")
        context['error'] = str(e)
    
    if request.method == 'POST':
        reference_number = sanitize_input(request.POST.get('reference_number'), 50)
        
        if not reference_number:
            messages.error(request, 'Please enter a reference number')
            return render(request, 'application-status.html', context)
        
        # Search in the already fetched applications
        found_app = None
        for app in all_applications:
            if app['reference'] == reference_number:
                found_app = app
                break
        
        if found_app:
            context['searched_app'] = found_app
            messages.success(request, f'Found application: {found_app["reference"]}')
        else:
            messages.error(request, f'No record found with reference number: {reference_number}')
    
    return render(request, 'application-status.html', context)


# ================= TRANSPORT & REVENUE SERVICES =================

@kiosk_login_required
def transport_services(request):
    """Transport services (under development)"""
    return render(request, 'under-development.html')


@kiosk_login_required
def revenue_services(request):
    """Revenue services (under development)"""
    return render(request, 'under-development.html')


# ================= PAYMENTS =================

@kiosk_login_required
def payment_history(request):
    """Payment history page"""
    filter_param = sanitize_input(request.GET.get('filter', 'all'), 20)
    consumer_id = request.session.get('consumer_id')
    
    payments = []
    
    # Try to fetch from database
    try:
        consumer = Consumer.objects.get(id=consumer_id)
        
        # Get electricity payments
        elec_payments = ElectricityPayment.objects.filter(bill__consumer__consumer=consumer).order_by('-payment_date')[:10]
        for payment in elec_payments:
            payments.append({
                'reference_no': payment.transaction_id,
                'service': 'electricity',
                'service_name': 'Electricity Bill',
                'date': payment.payment_date,
                'amount': payment.amount,
                'status': payment.status.lower()
            })
        
        # Get gas payments (from audit logs for now)
        gas_payments = AuditLog.objects.filter(
            consumer=consumer,
            action='GAS_PAYMENT'
        ).order_by('-created_at')[:5]
        
        for log in gas_payments:
            try:
                changes = log.changes
                payments.append({
                    'reference_no': changes.get('transaction', ''),
                    'service': 'gas',
                    'service_name': 'Gas Bill',
                    'date': log.created_at,
                    'amount': float(changes.get('amount', 0)),
                    'status': 'success'
                })
            except:
                pass
        
    except Exception as e:
        logger.error(f"Error fetching payments: {e}")
    
    # If no payments found, use sample data
    if not payments:
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
        filtered_payments = []
        for p in payments:
            if filter_param == 'gas' and p['service'] == 'gas':
                filtered_payments.append(p)
            elif filter_param == 'electricity' and p['service'] == 'electricity':
                filtered_payments.append(p)
            elif filter_param == 'water' and p['service'] == 'water':
                filtered_payments.append(p)
            elif filter_param == 'municipal' and p['service'] in ['property_tax', 'professional_tax', 'trade_license']:
                filtered_payments.append(p)
        payments = filtered_payments
    
    context = {
        'payments': payments,
        'filter': filter_param
    }
    
    return render(request, 'payment-history.html', context)


@kiosk_login_required
def receipt_print(request):
    """Print receipt"""
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


# ================= DOCUMENT UPLOADS =================

@kiosk_login_required
def document_upload_qr_view(request):
    """QR code document upload"""
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
    """Pen drive document upload"""
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
            
            # Log upload
            log_security_event(request, 'PEN_UPLOAD', {
                'count': len(valid_files),
                'files': ','.join(f.name for f in valid_files)
            })
            
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
    """Camera document capture and upload"""
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
            
            # Log upload
            log_security_event(request, 'CAMERA_UPLOAD', {
                'count': len(saved_images)
            })
            
            messages.success(request, f'Successfully uploaded {len(saved_images)} images!')
            
        except Exception as e:
            logger.error(f"Error processing camera images: {e}")
            messages.error(request, f'Error uploading images: {str(e)}')
            return render(request, 'document-upload-camera.html')
        
        return redirect('menu')
    
    return render(request, 'document-upload-camera.html')


# ================= UNDER DEVELOPMENT =================

@kiosk_login_required
def under_development(request):
    """View for under development pages"""
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