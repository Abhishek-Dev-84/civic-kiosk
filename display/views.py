from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
import random
from django.contrib.auth.decorators import login_required
import os
import json
import base64
from django.core.files.base import ContentFile
import datetime
from dateutil.relativedelta import relativedelta
from django.http import HttpResponseRedirect
from django.urls import reverse
from urllib.parse import urlparse, urlunparse


# ================= CORE / AUTH =================
def index(request):
    return render(request, 'index.html')

def auth(request):
    # Clear any existing messages
    storage = messages.get_messages(request)
    storage.used = True
    
    # CRITICAL: If there's ANY query parameter, redirect to clean URL
    if request.GET:
        return redirect('auth')
    
    if request.method == 'POST':
        aadhaar_number = request.POST.get('aadhaar_number')
        
        if aadhaar_number and len(aadhaar_number) == 12 and aadhaar_number.isdigit():
            request.session['aadhaar_number'] = aadhaar_number
            
            # Generate OTP (still generates but won't be checked)
            otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            request.session['otp'] = otp
            request.session['otp_attempts'] = 0
            
            print("\n" + "="*50)
            print(f"OTP for Aadhaar {aadhaar_number}: {otp}")
            print("="*50 + "\n")
            
            messages.success(request, 'OTP sent successfully')
            return redirect('otp')
        else:
            messages.error(request, 'Please enter a valid 12-digit Aadhaar number')
            return render(request, 'auth.html')
    
    # GET request - show the Aadhaar entry page
    return render(request, 'auth.html')


# ================= SIMPLIFIED OTP - ANY OTP WORKS =================
def otp(request):
    # Check if aadhaar is in session
    aadhaar_number = request.session.get('aadhaar_number')
    
    if not aadhaar_number:
        messages.error(request, 'Session expired. Please enter Aadhaar again.')
        return redirect('auth')
    
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        
        # SIMPLIFIED BYPASS: ANY NON-EMPTY OTP IS ACCEPTED
        if entered_otp and len(entered_otp) > 0:
            # OTP verified successfully - no checking!
            request.session['aadhaar_verified'] = True
            messages.success(request, 'OTP verified successfully!')
            return redirect('menu')
        else:
            messages.error(request, 'Please enter OTP')
    
    # Mask Aadhaar for display (show only last 4 digits)
    masked_aadhaar = 'XXXX XXXX ' + aadhaar_number[-4:]
    
    return render(request, 'otp.html', {'aadhaar': masked_aadhaar})

def resend_otp(request):
    if request.method == 'POST':
        # Get aadhaar from session
        aadhaar_number = request.session.get('aadhaar_number')
        
        if aadhaar_number:
            # Generate new OTP
            otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            request.session['otp'] = otp
            request.session['otp_attempts'] = 0  # Reset attempts
            
            # Print to console for testing
            print("\n" + "="*50)
            print(f"RESEND OTP for Aadhaar {aadhaar_number}: {otp}")
            print("="*50 + "\n")
            
            messages.success(request, 'New OTP sent successfully')
        else:
            messages.error(request, 'Session expired. Please login again.')
            return redirect('auth')
    
    return redirect('otp')


def menu(request):
    # Debug: Check Django auth
    print(f"User authenticated: {request.user.is_authenticated}")
    print(f"User: {request.user}")
    
    # Check if user is verified with Aadhaar
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    return render(request, 'menu.html')


# ================= ELECTRICITY =================

def electricity_services(request):
    # Check if user is verified
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    # Add some context data to ensure the page renders
    context = {
        'page_title': 'Electricity Services',
        'current_date': datetime.datetime.now().strftime('%d %b %Y'),
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
        
        # NEW FIELDS for payment method
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
                # Mask card number for display
                masked_card = 'XXXX XXXX XXXX ' + card_number[-4:] if len(card_number) >= 4 else 'XXXX'
                payment_details = f"Card: {masked_card}"
            else:
                messages.error(request, 'Please select a payment method')
                return render(request, 'electricity-bill-payment.html', context)
            
            messages.success(request, f'Payment of ₹{bill_amount} for consumer {consumer_number} successful! ({payment_details})')
            return redirect('electricity-services')
        
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
            return redirect(f'/electricity-bill-payment/?amount={bill_amount}&month={bill_month}')
        
        else:  # Search action
            consumer_number = request.POST.get('consumer_number')
            
            if not consumer_number or len(consumer_number) < 6:
                messages.error(request, 'Please enter a valid consumer number')
                return render(request, 'electricity-duplicate-bill.html', context)
            
            today = datetime.date.today()
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
                    'amount': f"{1200 + (i * 70):,}",
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
        if new_owner_email and '@' not in new_owner_email:
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
        
        if action == 'pay':
            consumer_no = request.POST.get('consumer_no')
            bill_amount = request.POST.get('bill_amount')
            messages.success(request, f'Water bill payment of ₹{bill_amount} successful!')
            return redirect('municipal-services')
        
        elif action == 'fetch':
            context = {
                'show_bill': True,
                'consumer_no': request.POST.get('consumer_no'),
                'consumer_name': 'Rajesh Kumar',
                'bill_number': f'WATER/{datetime.datetime.now().year}/{random.randint(1000, 9999)}',
                'bill_date': datetime.datetime.now().strftime('%d %b %Y'),
                'due_date': (datetime.datetime.now() + datetime.timedelta(days=15)).strftime('%d %b %Y'),
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
        
        if action == 'pay':
            property_id = request.POST.get('property_id')
            tax_amount = request.POST.get('tax_amount')
            messages.success(request, f'Property tax of ₹{tax_amount} paid successfully!')
            return redirect('municipal-services')
        
        elif action == 'fetch':
            context = {
                'show_tax': True,
                'property_id': request.POST.get('property_id'),
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
        
        if action == 'pay':
            ptin = request.POST.get('ptin')
            tax_amount = request.POST.get('tax_amount')
            messages.success(request, f'Professional tax of ₹{tax_amount} paid successfully!')
            return redirect('municipal-services')
        
        elif action == 'fetch':
            context = {
                'show_tax': True,
                'ptin': request.POST.get('ptin'),
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
    return render(request, 'application-status.html')


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
        
        messages.success(request, 'Building plan application submitted successfully!')
        return redirect('menu')
    
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
            context = {
                'show_subsidy': True,
                'consumer_no': consumer_no,
                'status': 'Active',
                'amount_per_cylinder': '200',
                'total_cylinders': '12',
                'remaining_cylinders': '3',
                'next_eligibility': '01 Apr 2026',
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
        
        today = datetime.date.today()
        
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
            booking = {
                'reference_number': reference_number,
                'booked_date': today.strftime('%d %b %Y') + ', 10:30 AM',
                'expected_delivery': (today + datetime.timedelta(days=2)).strftime('%d %b %Y') + ' by 6 PM',
                'delivery_person': 'Delivery team will be assigned soon',
                'cylinder_type': '14.2 kg Domestic Cylinder',
                'status': 'pending'
            }
        
        context['booking'] = booking
    
    return render(request, 'gas-booking-status.html', context)

def gas_bill_payment(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    
    if request.method == 'POST':
        messages.success(request, 'Gas bill payment successful!')
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
    
    # Sample payment data
    payments = [
        {
            'reference_no': 'PAY123456',
            'service': 'electricity',
            'service_name': 'Electricity Bill',
            'date': datetime.datetime.now() - datetime.timedelta(days=2),
            'amount': 1250.00,
            'status': 'success'
        },
        {
            'reference_no': 'PAY123457',
            'service': 'water',
            'service_name': 'Water Bill',
            'date': datetime.datetime.now() - datetime.timedelta(days=5),
            'amount': 450.00,
            'status': 'success'
        },
        {
            'reference_no': 'PAY123458',
            'service': 'gas',
            'service_name': 'Gas Bill',
            'date': datetime.datetime.now() - datetime.timedelta(days=7),
            'amount': 856.00,
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
        
        # Sample receipt data
        receipt = {
            'receipt_no': receipt_ref or 'RCPT123456',
            'datetime': datetime.datetime.now().strftime('%d %b %Y, %I:%M %p'),
            'service': '⚡ Electricity Bill',
            'consumer_no': '1234 5678 9012',
            'bill_period': 'Jan 2026',
            'payment_mode': 'UPI',
            'transaction_id': f'TXN{datetime.datetime.now().strftime("%y%m%d%H%M")}',
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
        
        messages.success(request, 'Birth certificate application submitted successfully!')
        return redirect('menu')
    
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
            death_date = date.fromisoformat(date_of_death)
            if death_date > date.today():
                messages.error(request, 'Date of death cannot be in the future')
                return render(request, 'death-certificate.html')
        
        messages.success(request, 'Death certificate application submitted successfully!')
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
        
        if not all([groom_name, bride_name, marriage_date, marriage_place, marriage_type]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'marriage-registration.html')
        
        ref_number = f"MAR{random.randint(100000, 999999)}"
        messages.success(request, f'Marriage registration submitted successfully! Reference: {ref_number}')
        return redirect('municipal-services')
    
    return render(request, 'marriage-registration.html')


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

# ================= ERROR HANDLERS =================

def custom_404(request, exception):
    """Custom 404 error handler"""
    return render(request, '404.html', status=404)

# Add this temporary test view (remove in production)
def test_404(request):
    """Test view to check 404 page"""
    return render(request, '404.html')


def under_development(request):
    """View for under development pages"""
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'under-development.html')