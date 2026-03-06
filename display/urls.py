from django.urls import path
from . import views

# Custom error handler - this will be used by the main project urls.py
handler404 = 'display.views.custom_404'

urlpatterns = [

    # ================= CORE / AUTH =================
    path('', views.index, name='index'),
    path('auth/', views.auth, name='auth'),
    path('otp/', views.otp, name='otp'),
    path('resend-otp/', views.resend_otp, name='resend-otp'),
    path('menu/', views.menu, name='menu'),

    # ================= ELECTRICITY =================
    path('electricity-bill-payment/', views.electricity_bill_payment, name='electricity-bill-payment'),
    path('electricity-duplicate-bill/', views.electricity_duplicate_bill, name='electricity-duplicate-bill'),
    path('electricity-solar/', views.electricity_solar, name='electricity-solar'),
    path('electricity-services/', views.electricity_services, name='electricity-services'),
    path('electricity-new-connection/', views.electricity_new_connection, name='electricity-new-connection'),
    path('electricity-name-transfer/', views.electricity_name_transfer, name='electricity-name-transfer'),
    path('electricity-meter-replacement/', views.electricity_meter_replacement, name='electricity-meter-replacement'),
    path('electricity-load-enhancement/', views.electricity_load_enhancement, name='electricity-load-enhancement'),
    path('electricity-complaint/', views.electricity_complaint, name='electricity-complaint'),

    # ================= WATER =================
    path('water-bill/', views.water_bill, name='water-bill'),

    # ================= MUNICIPAL SERVICES =================
    path('municipal-services/', views.municipal_services, name='municipal-services'),
    path('trade-license/', views.trade_license, name='trade-license'),
    path('property-tax/', views.property_tax, name='property-tax'),
    path('professional-tax/', views.professional_tax, name='professional-tax'),
    path('application-status/', views.application_status, name='application-status'),
    path('building-plan/', views.building_plan, name='building-plan'),

    # ================= GAS SERVICES =================
    path('gas-subsidy/', views.gas_subsidy, name='gas-subsidy'),
    path('gas-services/', views.gas_services, name='gas-services'),
    path('gas-new-connection/', views.gas_new_connection, name='gas-new-connection'),
    path('gas-cylinder-booking/', views.gas_cylinder_booking, name='gas-cylinder-booking'),
    path('gas-consumer-lookup/', views.gas_consumer_lookup, name='gas-consumer-lookup'),
    path('gas-complaint/', views.gas_complaint, name='gas-complaint'),
    path('gas-booking-status/', views.gas_bookings_status, name='gas-booking-status'),
    path('gas-bill-payment/', views.gas_bill_payment, name='gas-bill-payment'),

    # ================= TRANSPORT & REVENUE SERVICES =================
    path('transport-services/', views.under_development, name='under-development'),
    path('revenue-services/', views.under_development, name='under-development'),
    # ================= PAYMENTS =================
    path('payment-history/', views.payment_history, name='payment-history'),
    path('receipt-print/', views.receipt_print, name='receipt-print'),

    # ================= OTHER SERVICES / PAGES =================
    path('birth-certificate/', views.birth_certificate, name='birth-certificate'),
    path('death-certificate/', views.death_certificate, name='death-certificate'),
    path('marriage-registration/', views.marriage_registration, name='marriage-registration'),
    path('document-upload-qr/', views.document_upload_qr_view, name='document-upload-qr'),
    path('document-upload-pen/', views.document_upload_pen_view, name='document-upload-pen'),
    path('document-upload-camera/', views.document_upload_camera_view, name='document-upload-camera'),
    path('grievance/', views.grievance, name='grievance'),
    # TEMPORARY - remove after testing
    path('test-404/', views.test_404, name='test-404'),
    path('transport-services/', views.transport_services, name='transport-services'),
    path('revenue-services/', views.revenue_services, name='revenue-services'),

    
]