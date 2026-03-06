from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db import models
import json
from datetime import datetime
from . import models as kiosk_models


# ================= BASE ADMIN CLASSES =================

class ReadOnlyAdminMixin:
    """Mixin to make all fields read-only"""
    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editing an existing object
            return [f.name for f in self.model._meta.fields if f.name != 'id']
        return self.readonly_fields


class BaseModelAdmin(admin.ModelAdmin):
    """Base admin with common configurations"""
    list_per_page = 25
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related()


# ================= CONSUMER ADMIN =================

@admin.register(kiosk_models.Consumer)
class ConsumerAdmin(BaseModelAdmin):
    list_display = ['name', 'aadhaar_number', 'mobile', 'email', 'city', 'is_active', 'created_at']
    list_filter = ['gender', 'city', 'state', 'is_active']
    search_fields = ['name', 'aadhaar_number', 'mobile', 'email']
    readonly_fields = ['created_at', 'updated_at', 'last_login']
    fieldsets = (
        ('Personal Information', {
            'fields': ('name', 'father_name', 'mother_name', 'date_of_birth', 'gender')
        }),
        ('Identity', {
            'fields': ('aadhaar_number', 'email', 'mobile')
        }),
        ('Address', {
            'fields': ('address', 'city', 'state', 'pincode')
        }),
        ('Session Info', {
            'fields': ('last_login', 'session_token', 'is_active'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def view_connections(self, obj):
        """Button to view all connections"""
        return format_html(
            '<a class="button" href="{}?consumer__id__exact={}">View Connections</a>',
            reverse('admin:kiosk_electricityconsumer_changelist'),
            obj.id
        )
    view_connections.short_description = 'Connections'


# ================= ELECTRICITY ADMIN =================

@admin.register(kiosk_models.ElectricityConsumer)
class ElectricityConsumerAdmin(BaseModelAdmin):
    list_display = ['consumer_number', 'consumer_name', 'connection_type', 'sanctioned_load', 
                   'meter_type', 'is_active']
    list_filter = ['connection_type', 'meter_type', 'is_active']
    search_fields = ['consumer_number', 'consumer__name', 'consumer__aadhaar_number']
    raw_id_fields = ['consumer']
    readonly_fields = ['created_at', 'updated_at']
    
    def consumer_name(self, obj):
        return obj.consumer.name
    consumer_name.short_description = 'Name'
    consumer_name.admin_order_field = 'consumer__name'
    
    fieldsets = (
        ('Consumer Details', {
            'fields': ('consumer', 'consumer_number')
        }),
        ('Connection Details', {
            'fields': ('connection_type', 'sanctioned_load', 'current_meter_number', 'meter_type')
        }),
        ('Location', {
            'fields': ('address', 'connection_date')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_active', 'mark_inactive']
    
    def mark_active(self, request, queryset):
        queryset.update(is_active=True)
    mark_active.short_description = "Mark selected as Active"
    
    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)
    mark_inactive.short_description = "Mark selected as Inactive"


@admin.register(kiosk_models.ElectricityBill)
class ElectricityBillAdmin(BaseModelAdmin):
    list_display = ['bill_number', 'consumer_info', 'bill_date', 'due_date', 
                   'total_amount', 'paid_amount', 'status_colored']
    list_filter = ['status', 'bill_date', 'due_date']
    search_fields = ['bill_number', 'consumer__consumer_number', 'consumer__consumer__name']
    raw_id_fields = ['consumer']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'bill_date'
    
    def consumer_info(self, obj):
        return f"{obj.consumer.consumer_number} - {obj.consumer.consumer.name}"
    consumer_info.short_description = 'Consumer'
    consumer_info.admin_order_field = 'consumer__consumer_number'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'PAID': 'green',
            'OVERDUE': 'red',
            'DISPUTED': 'purple'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    fieldsets = (
        ('Bill Information', {
            'fields': ('consumer', 'bill_number')
        }),
        ('Dates', {
            'fields': ('bill_date', 'due_date', 'billing_period_start', 'billing_period_end')
        }),
        ('Usage & Charges', {
            'fields': ('units_consumed', 'rate_per_unit', 'fixed_charges', 'other_charges')
        }),
        ('Payment', {
            'fields': ('total_amount', 'paid_amount', 'status')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_paid', 'mark_as_overdue']
    
    def mark_as_paid(self, request, queryset):
        queryset.update(status='PAID', paid_amount=models.F('total_amount'))
    mark_as_paid.short_description = "Mark selected as Paid"
    
    def mark_as_overdue(self, request, queryset):
        queryset.update(status='OVERDUE')
    mark_as_overdue.short_description = "Mark selected as Overdue"


@admin.register(kiosk_models.ElectricityPayment)
class ElectricityPaymentAdmin(BaseModelAdmin):
    list_display = ['transaction_id', 'bill_link', 'amount', 'payment_method', 
                   'payment_date', 'status_colored']
    list_filter = ['payment_method', 'status', 'payment_date']
    search_fields = ['transaction_id', 'bill__bill_number']
    raw_id_fields = ['bill']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'payment_date'
    
    def bill_link(self, obj):
        url = reverse('admin:kiosk_electricitybill_change', args=[obj.bill.id])
        return format_html('<a href="{}">{}</a>', url, obj.bill.bill_number)
    bill_link.short_description = 'Bill'
    
    def status_colored(self, obj):
        colors = {
            'SUCCESS': 'green',
            'FAILED': 'red',
            'PENDING': 'orange',
            'REFUNDED': 'blue'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    fieldsets = (
        ('Payment Details', {
            'fields': ('bill', 'transaction_id', 'amount', 'payment_method')
        }),
        ('Payment Info', {
            'fields': ('payment_details', 'status')
        }),
        ('Timestamps', {
            'fields': ('payment_date', 'created_at', 'updated_at')
        }),
    )


@admin.register(kiosk_models.ElectricityComplaint)
class ElectricityComplaintAdmin(BaseModelAdmin):
    list_display = ['complaint_number', 'consumer_info', 'complaint_type', 
                   'priority_colored', 'status_colored', 'created_at']
    list_filter = ['complaint_type', 'priority', 'status']
    search_fields = ['complaint_number', 'consumer__consumer_number', 'description']
    raw_id_fields = ['consumer']
    readonly_fields = ['created_at', 'updated_at']
    
    def consumer_info(self, obj):
        return f"{obj.consumer.consumer_number}"
    consumer_info.short_description = 'Consumer'
    
    def priority_colored(self, obj):
        colors = {
            'NORMAL': 'green',
            'URGENT': 'orange',
            'EMERGENCY': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.priority, 'black'),
            obj.get_priority_display()
        )
    priority_colored.short_description = 'Priority'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'IN_PROGRESS': 'blue',
            'RESOLVED': 'green',
            'CLOSED': 'gray'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    fieldsets = (
        ('Complaint Info', {
            'fields': ('complaint_number', 'consumer', 'complaint_type', 'priority')
        }),
        ('Details', {
            'fields': ('description', 'contact_phone')
        }),
        ('Status', {
            'fields': ('status', 'assigned_officer', 'resolution_date', 'remarks')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['assign_to_me', 'mark_in_progress', 'mark_resolved']
    
    def assign_to_me(self, request, queryset):
        queryset.update(assigned_officer=request.user.get_full_name() or request.user.username)
    assign_to_me.short_description = "Assign selected to me"
    
    def mark_in_progress(self, request, queryset):
        queryset.update(status='IN_PROGRESS')
    mark_in_progress.short_description = "Mark as In Progress"
    
    def mark_resolved(self, request, queryset):
        from datetime import datetime
        queryset.update(status='RESOLVED', resolution_date=datetime.now())
    mark_resolved.short_description = "Mark as Resolved"


@admin.register(kiosk_models.LoadEnhancementRequest)
class LoadEnhancementRequestAdmin(BaseModelAdmin):
    list_display = ['request_number', 'consumer_info', 'current_load', 'requested_load', 
                   'status_colored', 'created_at']
    list_filter = ['status', 'reason']
    search_fields = ['request_number', 'consumer__consumer_number']
    raw_id_fields = ['consumer']
    
    def consumer_info(self, obj):
        return obj.consumer.consumer_number
    consumer_info.short_description = 'Consumer'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'APPROVED': 'green',
            'REJECTED': 'red',
            'INSPECTION_SCHEDULED': 'blue'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


@admin.register(kiosk_models.MeterReplacementRequest)
class MeterReplacementRequestAdmin(BaseModelAdmin):
    list_display = ['request_number', 'consumer_info', 'requested_meter_type', 
                   'preferred_date', 'total_cost', 'status_colored']
    list_filter = ['status', 'requested_meter_type']
    search_fields = ['request_number', 'consumer__consumer_number']
    raw_id_fields = ['consumer']
    
    def consumer_info(self, obj):
        return obj.consumer.consumer_number
    consumer_info.short_description = 'Consumer'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'APPROVED': 'green',
            'SCHEDULED': 'blue',
            'COMPLETED': 'gray',
            'CANCELLED': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


@admin.register(kiosk_models.NameTransferRequest)
class NameTransferRequestAdmin(BaseModelAdmin):
    list_display = ['request_number', 'consumer_info', 'new_owner_name', 
                   'total_amount', 'status_colored']
    list_filter = ['status', 'relationship']
    search_fields = ['request_number', 'consumer__consumer_number', 'new_owner_name']
    raw_id_fields = ['consumer']
    readonly_fields = ['sale_deed_preview', 'noc_preview', 'id_proof_preview', 'address_proof_preview']
    
    def consumer_info(self, obj):
        return obj.consumer.consumer_number
    consumer_info.short_description = 'Consumer'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'VERIFICATION': 'blue',
            'APPROVED': 'green',
            'REJECTED': 'red',
            'COMPLETED': 'gray'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    def sale_deed_preview(self, obj):
        if obj.sale_deed:
            return format_html('<a href="{}" target="_blank">View File</a>', obj.sale_deed.url)
        return "No file"
    sale_deed_preview.short_description = 'Sale Deed'
    
    def noc_preview(self, obj):
        if obj.noc:
            return format_html('<a href="{}" target="_blank">View File</a>', obj.noc.url)
        return "No file"
    noc_preview.short_description = 'NOC'
    
    def id_proof_preview(self, obj):
        if obj.id_proof:
            return format_html('<a href="{}" target="_blank">View File</a>', obj.id_proof.url)
        return "No file"
    id_proof_preview.short_description = 'ID Proof'
    
    def address_proof_preview(self, obj):
        if obj.address_proof:
            return format_html('<a href="{}" target="_blank">View File</a>', obj.address_proof.url)
        return "No file"
    address_proof_preview.short_description = 'Address Proof'


# ================= GAS ADMIN =================

@admin.register(kiosk_models.GasConsumer)
class GasConsumerAdmin(BaseModelAdmin):
    list_display = ['consumer_number', 'consumer_name', 'distributor', 
                   'subsidy_status', 'cylinders_remaining']
    list_filter = ['subsidy_status', 'distributor']
    search_fields = ['consumer_number', 'consumer__name', 'consumer__aadhaar_number']
    raw_id_fields = ['consumer']
    
    def consumer_name(self, obj):
        return obj.consumer.name
    consumer_name.short_description = 'Name'


@admin.register(kiosk_models.GasCylinderBooking)
class GasCylinderBookingAdmin(BaseModelAdmin):
    list_display = ['booking_number', 'consumer_info', 'cylinder_type', 
                   'cylinder_price', 'status_colored', 'booking_date']
    list_filter = ['status', 'cylinder_type']
    search_fields = ['booking_number', 'consumer__consumer_number']
    raw_id_fields = ['consumer']
    date_hierarchy = 'booking_date'
    
    def consumer_info(self, obj):
        return obj.consumer.consumer_number
    consumer_info.short_description = 'Consumer'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'PROCESSED': 'blue',
            'OUT_FOR_DELIVERY': 'purple',
            'DELIVERED': 'green',
            'CANCELLED': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


@admin.register(kiosk_models.GasSubsidy)
class GasSubsidyAdmin(BaseModelAdmin):
    list_display = ['consumer_info', 'amount_per_cylinder', 'cylinders_used', 
                   'next_eligible_date', 'is_active']
    list_filter = ['is_active']
    search_fields = ['consumer__consumer_number', 'consumer__consumer__name']
    raw_id_fields = ['consumer']
    
    def consumer_info(self, obj):
        return obj.consumer.consumer_number
    consumer_info.short_description = 'Consumer'


@admin.register(kiosk_models.GasComplaint)
class GasComplaintAdmin(BaseModelAdmin):
    list_display = ['complaint_number', 'consumer_info', 'complaint_type', 'status_colored', 'created_at']
    list_filter = ['status', 'complaint_type']
    search_fields = ['complaint_number', 'consumer__consumer_number']
    raw_id_fields = ['consumer']
    
    def consumer_info(self, obj):
        return obj.consumer.consumer_number
    consumer_info.short_description = 'Consumer'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'IN_PROGRESS': 'blue',
            'RESOLVED': 'green'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


# ================= WATER ADMIN =================

@admin.register(kiosk_models.WaterConsumer)
class WaterConsumerAdmin(BaseModelAdmin):
    list_display = ['consumer_number', 'consumer_name', 'property_type']
    list_filter = ['property_type']
    search_fields = ['consumer_number', 'consumer__name']
    raw_id_fields = ['consumer']
    
    def consumer_name(self, obj):
        return obj.consumer.name
    consumer_name.short_description = 'Name'


@admin.register(kiosk_models.WaterBill)
class WaterBillAdmin(BaseModelAdmin):
    list_display = ['bill_number', 'consumer_info', 'bill_date', 'due_date', 
                   'total_amount', 'status_colored']
    list_filter = ['status']
    search_fields = ['bill_number', 'consumer__consumer_number']
    raw_id_fields = ['consumer']
    date_hierarchy = 'bill_date'
    
    def consumer_info(self, obj):
        return obj.consumer.consumer_number
    consumer_info.short_description = 'Consumer'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'PAID': 'green',
            'OVERDUE': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


# ================= MUNICIPAL ADMIN =================

@admin.register(kiosk_models.Property)
class PropertyAdmin(BaseModelAdmin):
    list_display = ['property_id', 'owner_name', 'property_type', 'area_sqft', 'ward_number']
    list_filter = ['property_type', 'zone', 'ward_number']
    search_fields = ['property_id', 'consumer__name', 'address']
    raw_id_fields = ['consumer']
    
    def owner_name(self, obj):
        return obj.consumer.name
    owner_name.short_description = 'Owner'


@admin.register(kiosk_models.PropertyTax)
class PropertyTaxAdmin(BaseModelAdmin):
    list_display = ['tax_id', 'property_info', 'assessment_year', 'tax_amount', 
                   'due_date', 'status_colored']
    list_filter = ['status', 'assessment_year']
    search_fields = ['tax_id', 'property__property_id']
    raw_id_fields = ['property']
    date_hierarchy = 'due_date'
    
    def property_info(self, obj):
        return obj.property.property_id
    property_info.short_description = 'Property'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'PAID': 'green',
            'OVERDUE': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


@admin.register(kiosk_models.ProfessionalTax)
class ProfessionalTaxAdmin(BaseModelAdmin):
    list_display = ['ptin', 'consumer_name', 'profession', 'assessment_year', 
                   'half_yearly_tax', 'status_colored']
    list_filter = ['status', 'assessment_year']
    search_fields = ['ptin', 'consumer__name']
    raw_id_fields = ['consumer']
    date_hierarchy = 'due_date'
    
    def consumer_name(self, obj):
        return obj.consumer.name
    consumer_name.short_description = 'Name'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'PAID': 'green',
            'OVERDUE': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


@admin.register(kiosk_models.TradeLicense)
class TradeLicenseAdmin(BaseModelAdmin):
    list_display = ['license_number', 'business_name', 'owner_name', 'business_type', 
                   'issue_date', 'expiry_date', 'status_colored']
    list_filter = ['status', 'business_type']
    search_fields = ['license_number', 'business_name', 'owner_name']
    raw_id_fields = ['consumer']
    date_hierarchy = 'issue_date'
    
    def status_colored(self, obj):
        colors = {
            'ACTIVE': 'green',
            'EXPIRED': 'red',
            'SUSPENDED': 'orange'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


@admin.register(kiosk_models.BuildingPlanApplication)
class BuildingPlanApplicationAdmin(BaseModelAdmin):
    list_display = ['application_number', 'owner_name', 'building_type', 
                   'num_floors', 'status_colored', 'created_at']
    list_filter = ['status', 'building_type']
    search_fields = ['application_number', 'owner_name', 'survey_number']
    raw_id_fields = ['consumer']
    readonly_fields = ['building_plan_preview']
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'UNDER_REVIEW': 'blue',
            'APPROVED': 'green',
            'REJECTED': 'red',
            'MODIFICATION_REQUIRED': 'purple'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    def building_plan_preview(self, obj):
        if obj.building_plan_file:
            return format_html('<a href="{}" target="_blank">View Plan</a>', obj.building_plan_file.url)
        return "No file"
    building_plan_preview.short_description = 'Building Plan'


@admin.register(kiosk_models.Grievance)
class GrievanceAdmin(BaseModelAdmin):
    list_display = ['grievance_number', 'name', 'department', 'mobile', 
                   'status_colored', 'created_at']
    list_filter = ['status', 'department']
    search_fields = ['grievance_number', 'name', 'mobile']
    raw_id_fields = ['consumer']
    date_hierarchy = 'created_at'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'IN_PROGRESS': 'blue',
            'RESOLVED': 'green',
            'CLOSED': 'gray'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    fieldsets = (
        ('Grievance Info', {
            'fields': ('grievance_number', 'consumer', 'department')
        }),
        ('Personal Details', {
            'fields': ('name', 'mobile', 'location')
        }),
        ('Description', {
            'fields': ('description',)
        }),
        ('Status', {
            'fields': ('status', 'assigned_officer', 'resolution_date', 'remarks')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['assign_to_me', 'mark_in_progress', 'mark_resolved']
    
    def assign_to_me(self, request, queryset):
        queryset.update(assigned_officer=request.user.get_full_name() or request.user.username)
    assign_to_me.short_description = "Assign selected to me"
    
    def mark_in_progress(self, request, queryset):
        queryset.update(status='IN_PROGRESS')
    mark_in_progress.short_description = "Mark as In Progress"
    
    def mark_resolved(self, request, queryset):
        from datetime import datetime
        queryset.update(status='RESOLVED', resolution_date=datetime.now())
    mark_resolved.short_description = "Mark as Resolved"


@admin.register(kiosk_models.BirthCertificateApplication)
class BirthCertificateApplicationAdmin(BaseModelAdmin):
    list_display = ['application_number', 'child_name', 'date_of_birth', 
                   'father_name', 'status_colored']
    list_filter = ['status', 'gender']
    search_fields = ['application_number', 'child_name', 'father_name', 'mother_name']
    raw_id_fields = ['consumer']
    date_hierarchy = 'date_of_birth'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'APPROVED': 'green',
            'REJECTED': 'red',
            'ISSUED': 'blue'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


@admin.register(kiosk_models.DeathCertificateApplication)
class DeathCertificateApplicationAdmin(BaseModelAdmin):
    list_display = ['application_number', 'deceased_name', 'date_of_death', 
                   'father_name', 'status_colored']
    list_filter = ['status', 'gender']
    search_fields = ['application_number', 'deceased_name', 'father_name', 'mother_name']
    raw_id_fields = ['consumer']
    date_hierarchy = 'date_of_death'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'APPROVED': 'green',
            'REJECTED': 'red',
            'ISSUED': 'blue'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'


@admin.register(kiosk_models.MarriageRegistration)
class MarriageRegistrationAdmin(BaseModelAdmin):
    list_display = ['application_number', 'groom_name', 'bride_name', 
                   'marriage_date', 'marriage_type', 'status_colored']
    list_filter = ['status', 'marriage_type']
    search_fields = ['application_number', 'groom_name', 'bride_name']
    date_hierarchy = 'marriage_date'
    
    def status_colored(self, obj):
        colors = {
            'PENDING': 'orange',
            'APPROVED': 'green',
            'ISSUED': 'blue'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    fieldsets = (
        ('Application Info', {
            'fields': ('application_number', 'status', 'certificate_number')
        }),
        ('Groom Details', {
            'fields': ('groom_name', 'groom_dob', 'groom_aadhaar', 'groom_father_name')
        }),
        ('Bride Details', {
            'fields': ('bride_name', 'bride_dob', 'bride_aadhaar', 'bride_father_name')
        }),
        ('Marriage Details', {
            'fields': ('marriage_date', 'marriage_place', 'marriage_type', 
                      'witness1_name', 'witness2_name')
        }),
        ('Timestamps', {
            'fields': ('registration_date', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ================= DOCUMENT UPLOAD ADMIN =================

@admin.register(kiosk_models.DocumentUpload)
class DocumentUploadAdmin(BaseModelAdmin):
    list_display = ['upload_id', 'consumer_name', 'upload_type', 'file_name', 
                   'file_size_display', 'created_at']
    list_filter = ['upload_type']
    search_fields = ['upload_id', 'consumer__name', 'file_name']
    raw_id_fields = ['consumer']
    readonly_fields = ['file_preview']
    date_hierarchy = 'created_at'
    
    def consumer_name(self, obj):
        return obj.consumer.name if obj.consumer else 'Anonymous'
    consumer_name.short_description = 'Consumer'
    
    def file_size_display(self, obj):
        """Display file size in human readable format"""
        size = obj.file_size
        for unit in ['B', 'KB', 'MB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} GB"
    file_size_display.short_description = 'Size'
    
    def file_preview(self, obj):
        if obj.file:
            if obj.mime_type and obj.mime_type.startswith('image/'):
                return format_html('<img src="{}" style="max-height: 200px; max-width: 100%;" />', obj.file.url)
            return format_html('<a href="{}" target="_blank">Download File</a>', obj.file.url)
        return "No file"
    file_preview.short_description = 'Preview'


# ================= NOTIFICATION ADMIN =================

@admin.register(kiosk_models.Notification)
class NotificationAdmin(BaseModelAdmin):
    list_display = ['title', 'consumer_name', 'notification_type', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read']
    search_fields = ['title', 'message', 'consumer__name']
    raw_id_fields = ['consumer']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at']
    
    def consumer_name(self, obj):
        return obj.consumer.name if obj.consumer else 'Broadcast'
    consumer_name.short_description = 'Consumer'
    
    fieldsets = (
        ('Notification', {
            'fields': ('consumer', 'notification_type', 'title', 'message')
        }),
        ('Status', {
            'fields': ('is_read', 'read_at', 'action_url')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_read', 'mark_as_unread']
    
    def mark_as_read(self, request, queryset):
        from datetime import datetime
        queryset.update(is_read=True, read_at=datetime.now())
    mark_as_read.short_description = "Mark selected as Read"
    
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False, read_at=None)
    mark_as_unread.short_description = "Mark selected as Unread"


# ================= SESSION ADMIN =================

@admin.register(kiosk_models.UserSession)
class UserSessionAdmin(BaseModelAdmin):
    list_display = ['consumer_name', 'session_key_short', 'ip_address', 
                   'login_time', 'last_activity', 'is_active']
    list_filter = ['is_active']
    search_fields = ['consumer__name', 'session_key', 'ip_address']
    raw_id_fields = ['consumer']
    readonly_fields = ['session_key', 'ip_address', 'user_agent', 'login_time', 'last_activity']
    
    def consumer_name(self, obj):
        return obj.consumer.name if obj.consumer else 'Anonymous'
    consumer_name.short_description = 'Consumer'
    
    def session_key_short(self, obj):
        return obj.session_key[:20] + '...' if len(obj.session_key) > 20 else obj.session_key
    session_key_short.short_description = 'Session Key'
    
    actions = ['force_logout']
    
    def force_logout(self, request, queryset):
        from django.contrib.sessions.models import Session
        for session in queryset:
            try:
                Session.objects.filter(session_key=session.session_key).delete()
                session.is_active = False
                session.save()
            except:
                pass
        self.message_user(request, f"{queryset.count()} sessions terminated.")
    force_logout.short_description = "Force logout selected sessions"


# ================= AUDIT LOG ADMIN =================

@admin.register(kiosk_models.AuditLog)
class AuditLogAdmin(BaseModelAdmin):
    list_display = ['action', 'consumer_name', 'model_name', 'object_id', 
                   'ip_address', 'created_at']
    list_filter = ['action', 'model_name']
    search_fields = ['consumer__name', 'action', 'object_id', 'ip_address']
    raw_id_fields = ['consumer']
    readonly_fields = ['action', 'model_name', 'object_id', 'changes', 'ip_address', 
                      'user_agent', 'created_at']
    date_hierarchy = 'created_at'
    
    def consumer_name(self, obj):
        return obj.consumer.name if obj.consumer else 'Anonymous'
    consumer_name.short_description = 'Consumer'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    fieldsets = (
        ('Action Info', {
            'fields': ('action', 'model_name', 'object_id')
        }),
        ('Changes', {
            'fields': ('changes',),
            'classes': ('monospace',)
        }),
        ('Request Info', {
            'fields': ('consumer', 'ip_address', 'user_agent')
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )


# ================= CUSTOM ADMIN SITE CONFIGURATION =================

admin.site.site_header = 'Civic Kiosk Administration'
admin.site.site_title = 'Civic Kiosk Admin'
admin.site.index_title = 'Dashboard'