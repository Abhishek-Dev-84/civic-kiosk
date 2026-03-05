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
    # storage = messages.get_messages(request)
    # storage.used = True
    
    # # CRITICAL: If there's ANY query parameter, redirect to clean URL
    # if request.GET:
    #     return redirect('auth')
    
    # if request.method == 'POST':
    #     aadhaar_number = request.POST.get('aadhaar_number')
        
    #     if aadhaar_number and len(aadhaar_number) == 12 and aadhaar_number.isdigit():
    #         request.session['aadhaar_number'] = aadhaar_number
            
    #         # Generate OTP (still generates but won't be checked)
    #         otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    #         request.session['otp'] = otp
    #         request.session['otp_attempts'] = 0
            
    #         print("\n" + "="*50)
    #         print(f"OTP for Aadhaar {aadhaar_number}: {otp}")
    #         print("="*50 + "\n")
            
    #         messages.success(request, 'OTP sent successfully')
    #         return redirect('otp')
    #     else:
    #         messages.error(request, 'Please enter a valid 12-digit Aadhaar number')
    #         return render(request, 'auth.html')
    
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
        
        if action == 'pay':
            if not consumer_number or not bill_amount:
                messages.error(request, 'Invalid bill details')
                return render(request, 'electricity-bill-payment.html', context)
            
            messages.success(request, f'Payment of ₹{bill_amount} for consumer {consumer_number} successful!')
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
                    'amount': f"{1200 + (i * 70):,}"
                })
            
            context['bills'] = bills
            context['show_bills'] = True
            context['consumer_number'] = consumer_number
    
    return render(request, 'electricity-duplicate-bill.html', context)

def electricity_solar(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
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
        
        ref_number = f"TRAN{random.randint(100000, 999999)}"
        messages.success(request, f'Name transfer request submitted successfully! Reference: {ref_number}')
        return redirect('electricity-services')
    
    context['current_owner'] = 'Rajesh Kumar'
    context['consumer_number'] = '123456789012'
    context['address'] = '123, Gandhi Nagar'
    
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
        
        if not all([complaint_type, complaint_description]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'electricity-complaint.html')
        
        consumer_number_clean = consumer_number.replace(' ', '')
        if len(consumer_number_clean) < 6 or not consumer_number_clean.isdigit():
            messages.error(request, 'Please enter a valid consumer number')
            return render(request, 'electricity-complaint.html')
        
        ref_number = f"ELC{random.randint(100000, 999999)}"
        messages.success(request, f'Complaint registered successfully! Reference: {ref_number}')
        return redirect('electricity-services')
    
    return render(request, 'electricity-complaint.html')


# ================= WATER =================

def water_bill(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
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
    return render(request, 'trade-license.html')


def property_tax(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'property-tax.html')


def professional_tax(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
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
    return render(request, 'gas-subsidy.html')


def gas_new_connection(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'gas-new-connection.html')


def gas_cylinder_booking(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'gas-cylinder-booking.html')


def gas_consumer_lookup(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
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
    return render(request, 'payment-history.html')


def receipt_print(request):
    if not request.session.get('aadhaar_verified'):
        messages.error(request, 'Please verify OTP first')
        return redirect('auth')
    return render(request, 'receipt-print.html')


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
        relative_name = request.POST.get('relative_name')
        informant_name = request.POST.get('informant_name')
        informant_aadhaar = request.POST.get('informant_aadhaar')
        cause_of_death = request.POST.get('cause_of_death')
        
        if not all([deceased_name, date_of_death, place_of_death, gender, informant_name, informant_aadhaar]):
            messages.error(request, 'Please fill in all required fields')
            return render(request, 'death-certificate.html')
        
        if informant_aadhaar and (not informant_aadhaar.isdigit() or len(informant_aadhaar) != 12):
            messages.error(request, 'Please enter a valid 12-digit Aadhaar number')
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