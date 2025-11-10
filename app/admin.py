from django.contrib import admin
import os
from .models import (
    Website,
    DjangoProject,
    DeploymentLog,
    ServerResource,
    DatabaseBackup,
    SSLCertificate
)


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'title', 'subdomain', 'is_dynamic', 
        'custom_domain', 'is_active', 'created_at'
    )
    list_filter = ('is_active', 'is_dynamic', 'created_at')
    search_fields = ('title', 'subdomain', 'custom_domain', 'user__username')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(DjangoProject)
class DjangoProjectAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'project_name', 'python_version', 'subdomain',
        'deployment_status', 'is_active', 'created_at'
    )
    list_filter = ('deployment_status', 'is_active', 'python_version', 'created_at')
    search_fields = (
        'project_name', 'subdomain', 'custom_domain', 
        'domain_name', 'user__username'
    )
    readonly_fields = ('created_at', 'updated_at', 'last_deployed')
    ordering = ('-created_at',)


@admin.register(DeploymentLog)
class DeploymentLogAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'log_type', 'created_at', 'get_project_name'
    )
    list_filter = ('log_type', 'created_at')
    search_fields = ('message', 'user__username')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

    def get_project_name(self, obj):
        if obj.website:
            return obj.website.title
        elif obj.django_project:
            return obj.django_project.project_name
        return "-"
    get_project_name.short_description = "Project/Website"


@admin.register(ServerResource)
class ServerResourceAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'cpu_usage', 'memory_usage', 
        'disk_usage', 'bandwidth_usage', 'recorded_at'
    )
    list_filter = ('recorded_at',)
    search_fields = ('user__username',)
    readonly_fields = ('recorded_at',)
    ordering = ('-recorded_at',)


@admin.register(DatabaseBackup)
class DatabaseBackupAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'django_project', 'backup_size', 
        'is_automatic', 'created_at'
    )
    list_filter = ('is_automatic', 'created_at')
    search_fields = ('django_project__project_name',)
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


@admin.register(SSLCertificate)
class SSLCertificateAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'domain', 'issued_at', 'expires_at', 
        'is_active', 'auto_renew', 'created_at'
    )
    list_filter = ('is_active', 'auto_renew', 'created_at')
    search_fields = ('domain',)
    readonly_fields = ('created_at', 'last_renewal_attempt')
    ordering = ('-created_at',)


###########################storage##############################

from django.contrib import admin
from .models import UserFile, StorageSettings, PaymentRequest

@admin.register(UserFile)
class UserFileAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'uploaded_at', 'file_size_mb')
    list_filter = ('uploaded_at', 'user')
    search_fields = ('title', 'user__username')
    readonly_fields = ('uploaded_at',)

    def file_size_mb(self, obj):
        if obj.file and os.path.exists(obj.file.path):
            return f"{obj.file.size / (1024 * 1024):.2f} MB"
        return "(File Missing)"
    file_size_mb.short_description = "File Size"


@admin.register(StorageSettings)
class StorageSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'price_per_gb', 'free_limit_gb', 'updated_at')
    list_editable = ('price_per_gb', 'free_limit_gb')
    list_display_links = ('id',)
    list_filter = ('updated_at',)
    search_fields = ('price_per_gb',)


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'gb_requested', 'status', 'requested_at')
    list_filter = ('status', 'requested_at')
    search_fields = ('user__username',)
    readonly_fields = ('requested_at', 'amount', 'qr_image')
    actions = ['approve_payments', 'reject_payments']

    @admin.action(description='Approve selected payments')
    def approve_payments(self, request, queryset):
        updated = queryset.update(status='approved')
        self.message_user(request, f"{updated} payment(s) approved.")

    @admin.action(description='Reject selected payments')
    def reject_payments(self, request, queryset):
        updated = queryset.update(status='rejected')
        self.message_user(request, f"{updated} payment(s) rejected.")



##########################Github Integration###########################
from .models import DeployedProject
@admin.register(DeployedProject)
class DeployedProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "port", "repo_url", "running", "created_at")
    readonly_fields = ("created_at",)