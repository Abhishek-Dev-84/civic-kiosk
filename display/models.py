from django.db import models
from django.contrib.auth.models import User
import uuid
import datetime

# ================= BASE MODELS =================

class BaseModel(models.Model):
    """Base model with common fields"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class Consumer(BaseModel):
    """Consumer information linked to Aadhaar"""
    aadhaar_number = models.CharField(max_length=12, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    father_name = models.CharField(max_length=100, blank=True)
    mother_name = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=[
        ('MALE', 'Male'), ('FEMALE', 'Female'), ('OTHER', 'Other')
    ])
    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=10, blank=True)
    address = models.TextField()
    city = models.CharField(max_length=50)
    state = models.CharField(max_length=50)
    pincode = models.CharField(max_length=6)
    
    # Metadata
    last_login = models.DateTimeField(null=True, blank=True)
    session_token = models.CharField(max_length=100, blank=True)
    
    def __str__(self):
        return f"{self.name} - {self.aadhaar_number[-4:]}"
    
    class Meta:
        indexes = [
            models.Index(fields=['aadhaar_number']),
            models.Index(fields=['mobile']),
            models.Index(fields=['email']),
        ]


# ================= ELECTRICITY MODELS =================

class ElectricityConsumer(BaseModel):
    """Electricity consumer details"""
    consumer = models.OneToOneField(Consumer, on_delete=models.CASCADE, related_name='electricity_connection')
    consumer_number = models.CharField(max_length=20, unique=True, db_index=True)
    connection_type = models.CharField(max_length=20, choices=[
        ('RESIDENTIAL', 'Residential'),
        ('COMMERCIAL', 'Commercial'),
        ('INDUSTRIAL', 'Industrial'),
        ('AGRICULTURAL', 'Agricultural'),
    ], default='RESIDENTIAL')
    sanctioned_load = models.DecimalField(max_digits=10, decimal_places=2, default=3.0)  # in kW
    current_meter_number = models.CharField(max_length=50, blank=True)
    meter_type = models.CharField(max_length=20, choices=[
        ('SINGLE_PHASE', 'Single Phase'),
        ('THREE_PHASE', 'Three Phase'),
        ('SMART', 'Smart Meter'),
        ('CT', 'CT Meter'),
    ], default='SINGLE_PHASE')
    connection_date = models.DateField(null=True, blank=True)
    address = models.TextField()
    
    def __str__(self):
        return f"{self.consumer_number} - {self.consumer.name}"


class ElectricityBill(BaseModel):
    """Electricity bills"""
    consumer = models.ForeignKey(ElectricityConsumer, on_delete=models.CASCADE, related_name='bills')
    bill_number = models.CharField(max_length=50, unique=True, db_index=True)
    bill_date = models.DateField()
    due_date = models.DateField()
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    units_consumed = models.IntegerField()
    rate_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    fixed_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('DISPUTED', 'Disputed'),
    ], default='PENDING')
    
    def __str__(self):
        return f"{self.bill_number} - ₹{self.total_amount}"
    
    class Meta:
        ordering = ['-bill_date']


class ElectricityPayment(BaseModel):
    """Electricity payments"""
    bill = models.ForeignKey(ElectricityBill, on_delete=models.CASCADE, related_name='payments')
    transaction_id = models.CharField(max_length=50, unique=True, db_index=True)
    payment_date = models.DateTimeField(auto_now_add=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=[
        ('UPI', 'UPI'),
        ('CARD', 'Card'),
        ('NETBANKING', 'Net Banking'),
        ('CASH', 'Cash'),
    ])
    payment_details = models.JSONField(default=dict)  # Stores UPI ID, card last 4 digits, etc.
    status = models.CharField(max_length=300, choices=[
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('PENDING', 'Pending'),
        ('REFUNDED', 'Refunded'),
    ], default='SUCCESS')
    
    def __str__(self):
        return f"{self.transaction_id} - ₹{self.amount}"


class ElectricityComplaint(BaseModel):
    """Electricity complaints"""
    consumer = models.ForeignKey(ElectricityConsumer, on_delete=models.CASCADE, related_name='complaints')
    complaint_number = models.CharField(max_length=50, unique=True, db_index=True)
    complaint_type = models.CharField(max_length=50, choices=[
        ('NO_POWER', 'No Power'),
        ('VOLTAGE_ISSUE', 'Voltage Issue'),
        ('METER_PROBLEM', 'Meter Problem'),
        ('BILLING_ISSUE', 'Billing Issue'),
        ('POLE_WIRE_ISSUE', 'Pole/Wire Issue'),
        ('OTHER', 'Other'),
    ])
    priority = models.CharField(max_length=20, choices=[
        ('NORMAL', 'Normal'),
        ('URGENT', 'Urgent'),
        ('EMERGENCY', 'Emergency'),
    ], default='NORMAL')
    description = models.TextField()
    contact_phone = models.CharField(max_length=10)
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    ], default='PENDING')
    assigned_officer = models.CharField(max_length=100, blank=True)
    resolution_date = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    
    def __str__(self):
        return f"{self.complaint_number} - {self.complaint_type}"


class LoadEnhancementRequest(BaseModel):
    """Load enhancement requests"""
    consumer = models.ForeignKey(ElectricityConsumer, on_delete=models.CASCADE, related_name='load_requests')
    request_number = models.CharField(max_length=50, unique=True, db_index=True)
    current_load = models.DecimalField(max_digits=10, decimal_places=2)
    requested_load = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=50, choices=[
        ('NEW_APPLIANCES', 'New Appliances'),
        ('HOME_EXTENSION', 'Home Extension'),
        ('COMMERCIAL_ACTIVITY', 'Commercial Activity'),
        ('EV_CHARGER', 'EV Charger'),
        ('OTHER', 'Other'),
    ])
    reason_details = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('INSPECTION_SCHEDULED', 'Inspection Scheduled'),
    ], default='PENDING')
    inspection_date = models.DateField(null=True, blank=True)
    approved_load = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fee_amount = models.DecimalField(max_digits=10, decimal_places=2)
    remarks = models.TextField(blank=True)
    
    def __str__(self):
        return f"{self.request_number} - {self.current_load}→{self.requested_load}kW"


class MeterReplacementRequest(BaseModel):
    """Meter replacement requests"""
    consumer = models.ForeignKey(ElectricityConsumer, on_delete=models.CASCADE, related_name='meter_requests')
    request_number = models.CharField(max_length=50, unique=True, db_index=True)
    reason = models.CharField(max_length=50, choices=[
        ('FAULTY', 'Meter faulty/not working'),
        ('DAMAGED', 'Meter damaged'),
        ('UPGRADE', 'Upgrade to smart meter'),
        ('ERROR', 'Meter showing error'),
        ('STOLEN', 'Meter stolen'),
        ('OTHER', 'Other'),
    ])
    current_meter_type = models.CharField(max_length=20)
    requested_meter_type = models.CharField(max_length=20, choices=[
        ('SINGLE_PHASE', 'Single Phase'),
        ('THREE_PHASE', 'Three Phase'),
        ('SMART', 'Smart Meter'),
        ('CT', 'CT Meter'),
    ])
    meter_price = models.DecimalField(max_digits=10, decimal_places=2)
    preferred_date = models.DateField()
    preferred_time = models.CharField(max_length=20, choices=[
        ('09:00-12:00', '09:00 - 12:00'),
        ('12:00-15:00', '12:00 - 15:00'),
        ('15:00-18:00', '15:00 - 18:00'),
    ])
    additional_services = models.JSONField(default=list)  # ['calibration', 'wiring', 'seal']
    installation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=500)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('SCHEDULED', 'Scheduled'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ], default='PENDING')
    
    def __str__(self):
        return f"{self.request_number} - {self.requested_meter_type}"


class NameTransferRequest(BaseModel):
    """Name transfer requests"""
    consumer = models.ForeignKey(ElectricityConsumer, on_delete=models.CASCADE, related_name='transfer_requests')
    request_number = models.CharField(max_length=50, unique=True, db_index=True)
    new_owner_name = models.CharField(max_length=100)
    new_owner_aadhaar = models.CharField(max_length=12)
    new_owner_phone = models.CharField(max_length=10)
    new_owner_email = models.EmailField(blank=True)
    relationship = models.CharField(max_length=50, choices=[
        ('PURCHASER', 'Purchaser'),
        ('FAMILY_MEMBER', 'Family Member'),
        ('LEGAL_HEIR', 'Legal Heir'),
        ('OTHER', 'Other'),
    ])
    transfer_fee = models.DecimalField(max_digits=10, decimal_places=2, default=500)
    document_fee = models.DecimalField(max_digits=10, decimal_places=2, default=200)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Document uploads
    sale_deed = models.FileField(upload_to='documents/name_transfer/sale_deed/', blank=True)
    noc = models.FileField(upload_to='documents/name_transfer/noc/', blank=True)
    id_proof = models.FileField(upload_to='documents/name_transfer/id_proof/', blank=True)
    address_proof = models.FileField(upload_to='documents/name_transfer/address_proof/', blank=True)
    
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('VERIFICATION', 'Under Verification'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('COMPLETED', 'Completed'),
    ], default='PENDING')
    
    def __str__(self):
        return f"{self.request_number} - {self.new_owner_name}"


# ================= GAS MODELS =================

class GasConsumer(BaseModel):
    """Gas consumer details"""
    consumer = models.OneToOneField(Consumer, on_delete=models.CASCADE, related_name='gas_connection')
    consumer_number = models.CharField(max_length=20, unique=True, db_index=True)
    distributor = models.CharField(max_length=100)
    distributor_code = models.CharField(max_length=20)
    subsidy_status = models.BooleanField(default=True)
    subsidy_amount = models.DecimalField(max_digits=10, decimal_places=2, default=200)
    total_cylinders_per_year = models.IntegerField(default=12)
    cylinders_remaining = models.IntegerField(default=12)
    address = models.TextField()
    
    def __str__(self):
        return f"{self.consumer_number} - {self.consumer.name}"


class GasCylinderBooking(BaseModel):
    """Gas cylinder bookings"""
    consumer = models.ForeignKey(GasConsumer, on_delete=models.CASCADE, related_name='bookings')
    booking_number = models.CharField(max_length=50, unique=True, db_index=True)
    cylinder_type = models.CharField(max_length=20, choices=[
        ('14.2KG_DOMESTIC', '14.2 kg Domestic'),
        ('5KG_DOMESTIC', '5 kg Domestic'),
        ('19KG_COMMERCIAL', '19 kg Commercial'),
    ])
    cylinder_price = models.DecimalField(max_digits=10, decimal_places=2)
    booking_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('PROCESSED', 'Processed'),
        ('OUT_FOR_DELIVERY', 'Out for Delivery'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    ], default='PENDING')
    expected_delivery_date = models.DateField(null=True, blank=True)
    delivery_person = models.CharField(max_length=100, blank=True)
    delivery_person_phone = models.CharField(max_length=10, blank=True)
    actual_delivery_date = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.booking_number} - {self.cylinder_type}"


class GasComplaint(BaseModel):
    """Gas complaints"""
    consumer = models.ForeignKey(GasConsumer, on_delete=models.CASCADE, related_name='complaints')
    complaint_number = models.CharField(max_length=50, unique=True, db_index=True)
    complaint_type = models.CharField(max_length=50, choices=[
        ('LEAKAGE', 'Gas Leakage'),
        ('CYLINDER_ISSUE', 'Cylinder Issue'),
        ('REGULATOR_FAULT', 'Regulator Fault'),
        ('BILLING_ISSUE', 'Billing Issue'),
        ('DELIVERY_DELAY', 'Delivery Delay'),
        ('OTHER', 'Other'),
    ])
    description = models.TextField()
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
    ], default='PENDING')
    
    def __str__(self):
        return f"{self.complaint_number} - {self.complaint_type}"


class GasSubsidy(models.Model):
    """Gas subsidy records"""
    consumer = models.OneToOneField(GasConsumer, on_delete=models.CASCADE, related_name='subsidy')
    is_active = models.BooleanField(default=True)
    amount_per_cylinder = models.DecimalField(max_digits=10, decimal_places=2)
    total_cylinders_allotted = models.IntegerField()
    cylinders_used = models.IntegerField(default=0)
    last_claim_date = models.DateField(null=True, blank=True)
    next_eligible_date = models.DateField()
    bank_account_number = models.CharField(max_length=20)
    bank_ifsc = models.CharField(max_length=11)
    
    def __str__(self):
        return f"{self.consumer.consumer_number} - ₹{self.amount_per_cylinder}"


# ================= WATER MODELS =================

class WaterConsumer(BaseModel):
    """Water consumer details"""
    consumer = models.OneToOneField(Consumer, on_delete=models.CASCADE, related_name='water_connection')
    consumer_number = models.CharField(max_length=20, unique=True, db_index=True)
    property_type = models.CharField(max_length=20, choices=[
        ('RESIDENTIAL', 'Residential'),
        ('COMMERCIAL', 'Commercial'),
        ('INDUSTRIAL', 'Industrial'),
    ])
    meter_number = models.CharField(max_length=50, blank=True)
    connection_date = models.DateField()
    address = models.TextField()
    
    def __str__(self):
        return f"{self.consumer_number} - {self.consumer.name}"


class WaterBill(BaseModel):
    """Water bills"""
    consumer = models.ForeignKey(WaterConsumer, on_delete=models.CASCADE, related_name='bills')
    bill_number = models.CharField(max_length=50, unique=True)
    bill_date = models.DateField()
    due_date = models.DateField()
    units_consumed = models.IntegerField()  # in kiloliters
    rate_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    fixed_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
    ], default='PENDING')
    
    def __str__(self):
        return f"{self.bill_number} - ₹{self.total_amount}"


# ================= MUNICIPAL MODELS =================

class Property(BaseModel):
    """Property records for tax"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='properties')
    property_id = models.CharField(max_length=20, unique=True, db_index=True)
    property_type = models.CharField(max_length=20, choices=[
        ('RESIDENTIAL', 'Residential'),
        ('COMMERCIAL', 'Commercial'),
        ('INDUSTRIAL', 'Industrial'),
        ('AGRICULTURAL', 'Agricultural'),
    ])
    area_sqft = models.IntegerField()
    address = models.TextField()
    zone = models.CharField(max_length=50)
    ward_number = models.CharField(max_length=10)
    assessment_year = models.CharField(max_length=9)  # e.g., "2025-26"
    
    def __str__(self):
        return f"{self.property_id} - {self.property_type}"


class PropertyTax(BaseModel):
    """Property tax records"""
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='taxes')
    tax_id = models.CharField(max_length=20, unique=True)
    assessment_year = models.CharField(max_length=9)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
    ], default='PENDING')
    
    def __str__(self):
        return f"{self.tax_id} - ₹{self.tax_amount}"


class ProfessionalTax(BaseModel):
    """Professional tax records"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='professional_taxes')
    ptin = models.CharField(max_length=20, unique=True)  # Professional Tax Identification Number
    profession = models.CharField(max_length=100)
    employer_name = models.CharField(max_length=100, blank=True)
    assessment_year = models.CharField(max_length=9)
    half_yearly_tax = models.DecimalField(max_digits=10, decimal_places=2)
    penalty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    due_date = models.DateField()
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
    ], default='PENDING')
    
    def __str__(self):
        return f"{self.ptin} - ₹{self.half_yearly_tax}"


class TradeLicense(BaseModel):
    """Trade license records"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='trade_licenses')
    license_number = models.CharField(max_length=20, unique=True)
    business_name = models.CharField(max_length=100)
    business_type = models.CharField(max_length=50, choices=[
        ('RETAIL_SHOP', 'Retail Shop'),
        ('RESTAURANT', 'Restaurant'),
        ('MANUFACTURING', 'Manufacturing'),
        ('SERVICE_PROVIDER', 'Service Provider'),
        ('WAREHOUSE', 'Warehouse'),
        ('OTHER', 'Other'),
    ])
    owner_name = models.CharField(max_length=100)
    address = models.TextField()
    gst_number = models.CharField(max_length=15, blank=True)
    issue_date = models.DateField()
    expiry_date = models.DateField()
    license_fee = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=30, choices=[
        ('ACTIVE', 'Active'),
        ('EXPIRED', 'Expired'),
        ('SUSPENDED', 'Suspended'),
    ], default='ACTIVE')
    
    def __str__(self):
        return f"{self.license_number} - {self.business_name}"


class BuildingPlanApplication(BaseModel):
    """Building plan approval applications"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='building_plans')
    application_number = models.CharField(max_length=20, unique=True)
    owner_name = models.CharField(max_length=100)
    property_address = models.TextField()
    survey_number = models.CharField(max_length=50)
    plot_area = models.DecimalField(max_digits=10, decimal_places=2)  # in sq meters
    building_type = models.CharField(max_length=20, choices=[
        ('RESIDENTIAL', 'Residential'),
        ('COMMERCIAL', 'Commercial'),
        ('MIXED_USE', 'Mixed Use'),
        ('INDUSTRIAL', 'Industrial'),
    ])
    num_floors = models.IntegerField()
    building_plan_file = models.FileField(upload_to='documents/building_plans/')
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('UNDER_REVIEW', 'Under Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('MODIFICATION_REQUIRED', 'Modification Required'),
    ], default='PENDING')
    remarks = models.TextField(blank=True)
    
    def __str__(self):
        return f"{self.application_number} - {self.owner_name}"


class Grievance(BaseModel):
    """General grievances"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='grievances')
    grievance_number = models.CharField(max_length=20, unique=True)
    department = models.CharField(max_length=50, choices=[
        ('WATER', 'Water'),
        ('SEWAGE', 'Sewage'),
        ('ROADS', 'Roads'),
        ('STREET_LIGHT', 'Street Light'),
        ('GARBAGE', 'Garbage'),
        ('OTHER', 'Other'),
    ])
    name = models.CharField(max_length=100)
    mobile = models.CharField(max_length=10)
    location = models.TextField()
    description = models.TextField()
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    ], default='PENDING')
    assigned_officer = models.CharField(max_length=100, blank=True)
    resolution_date = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    
    def __str__(self):
        return f"{self.grievance_number} - {self.department}"


class BirthCertificateApplication(BaseModel):
    """Birth certificate applications"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='birth_certificates')
    application_number = models.CharField(max_length=20, unique=True)
    child_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=[
        ('MALE', 'Male'), ('FEMALE', 'Female'), ('OTHER', 'Other')
    ])
    place_of_birth = models.CharField(max_length=100)
    father_name = models.CharField(max_length=100)
    mother_name = models.CharField(max_length=100)
    permanent_address = models.TextField()
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('ISSUED', 'Issued'),
    ], default='PENDING')
    certificate_number = models.CharField(max_length=50, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.application_number} - {self.child_name}"


class DeathCertificateApplication(BaseModel):
    """Death certificate applications"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='death_certificates')
    application_number = models.CharField(max_length=20, unique=True)
    deceased_name = models.CharField(max_length=100)
    date_of_death = models.DateField()
    place_of_death = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, choices=[
        ('MALE', 'Male'), ('FEMALE', 'Female'), ('OTHER', 'Other')
    ])
    father_name = models.CharField(max_length=100)
    mother_name = models.CharField(max_length=100)
    permanent_address = models.TextField()
    cause_of_death = models.TextField()
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('ISSUED', 'Issued'),
    ], default='PENDING')
    certificate_number = models.CharField(max_length=50, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.application_number} - {self.deceased_name}"


class MarriageRegistration(BaseModel):
    """Marriage registrations"""
    application_number = models.CharField(max_length=20, unique=True)
    groom_name = models.CharField(max_length=100)
    groom_dob = models.DateField()
    groom_aadhaar = models.CharField(max_length=12)
    groom_father_name = models.CharField(max_length=100, blank=True)
    bride_name = models.CharField(max_length=100)
    bride_dob = models.DateField()
    bride_aadhaar = models.CharField(max_length=12)
    bride_father_name = models.CharField(max_length=100, blank=True)
    marriage_date = models.DateField()
    marriage_place = models.CharField(max_length=100)
    marriage_type = models.CharField(max_length=50, choices=[
        ('HINDU_MARRIAGE_ACT', 'Hindu Marriage Act'),
        ('SPECIAL_MARRIAGE_ACT', 'Special Marriage Act'),
        ('MUSLIM_PERSONAL_LAW', 'Muslim Personal Law'),
        ('CHRISTIAN_MARRIAGE_ACT', 'Christian Marriage Act'),
        ('OTHER', 'Other'),
    ])
    witness1_name = models.CharField(max_length=100, blank=True)
    witness2_name = models.CharField(max_length=100, blank=True)
    registration_date = models.DateField(auto_now_add=True)
    certificate_number = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=30, choices=[
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('ISSUED', 'Issued'),
    ], default='PENDING')
    
    def __str__(self):
        return f"{self.application_number} - {self.groom_name} & {self.bride_name}"


# ================= DOCUMENT UPLOADS =================

class DocumentUpload(BaseModel):
    """Generic document uploads"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='documents')
    upload_id = models.CharField(max_length=50, unique=True, default=uuid.uuid4)
    upload_type = models.CharField(max_length=20, choices=[
        ('QR', 'QR Upload'),
        ('PEN_DRIVE', 'Pen Drive'),
        ('CAMERA', 'Camera'),
        ('MANUAL', 'Manual'),
    ])
    file = models.FileField(upload_to='uploads/')
    file_name = models.CharField(max_length=255)
    file_size = models.IntegerField()  # in bytes
    mime_type = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    
    def __str__(self):
        return f"{self.upload_id} - {self.file_name}"


# ================= SESSION MANAGEMENT =================

class UserSession(BaseModel):
    """User session tracking"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='sessions')
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    login_time = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.consumer.name} - {self.login_time}"


# ================= NOTIFICATIONS =================

class Notification(BaseModel):
    """User notifications"""
    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=50, choices=[
        ('PAYMENT_SUCCESS', 'Payment Success'),
        ('PAYMENT_FAILED', 'Payment Failed'),
        ('APPLICATION_UPDATE', 'Application Update'),
        ('COMPLAINT_UPDATE', 'Complaint Update'),
        ('BILL_DUE', 'Bill Due'),
        ('GENERAL', 'General'),
    ])
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    action_url = models.CharField(max_length=200, blank=True)
    
    def __str__(self):
        return f"{self.consumer.name} - {self.title}"
    
    class Meta:
        ordering = ['-created_at']


# ================= AUDIT LOGS =================

class AuditLog(BaseModel):
    """Audit logs for all actions"""
    consumer = models.ForeignKey(Consumer, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    action = models.CharField(max_length=100)
    model_name = models.CharField(max_length=50)
    object_id = models.CharField(max_length=50)
    changes = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    
    def __str__(self):
        return f"{self.action} - {self.model_name} - {self.created_at}"