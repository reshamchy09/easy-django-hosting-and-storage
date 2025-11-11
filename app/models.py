from django.db import models
from django.contrib.auth.models import User
import os
from django.utils.text import slugify



def upload_to(instance, filename):
    return f'user_uploads/{instance.user.username}/{filename}'


class UserFile(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=400)
    file = models.FileField(upload_to=upload_to, max_length=500)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    @property
    def size(self):
        return self.file.size  # Size in bytes


class StorageSettings(models.Model):
    price_per_gb = models.DecimalField(max_digits=10, decimal_places=2, default=5.00)
    free_limit_gb = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Storage Settings (Last Updated: {self.updated_at.strftime('%Y-%m-%d %H:%M:%S')})"


class PaymentRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    gb_requested = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    qr_image = models.ImageField(upload_to='payment_qr/')  # Admin QR image
    payment_proof = models.ImageField(upload_to='payment_proofs/', null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.status} - ${self.amount}"


    
 #########################################################
 # Models for Static Website and Django Project Hosting   
class Website(models.Model):
    """Static website model"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    subdomain = models.CharField(max_length=100, unique=True)
    uploaded_file = models.FileField(upload_to='website_uploads/')
    is_dynamic = models.BooleanField(default=False)
    custom_domain = models.CharField(max_length=200, blank=True, null=True)
    folder_name = models.CharField(max_length=500, blank=True, null=True)
    domain_name = models.CharField(max_length=200, blank=True, null=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.title}"

    def get_site_url(self):
        if self.domain_name:
            return f"http://{self.domain_name}"
        return None

    class Meta:
        ordering = ['-created_at']


class DjangoProject(models.Model):
    """Django project hosting model"""
    
    DEPLOYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('building', 'Building'),
        ('deployed', 'Deployed'),
        ('failed', 'Failed'),
        ('stopped', 'Stopped'),
    ]
    
    PYTHON_VERSION_CHOICES = [
        ('3.8', 'Python 3.8'),
        ('3.9', 'Python 3.9'),
        ('3.10', 'Python 3.10'),
        ('3.11', 'Python 3.11'),
        ('3.12', 'Python 3.12'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    project_name = models.CharField(max_length=200, help_text="Name of your Django project")
    description = models.TextField(blank=True, help_text="Brief description of your project")
    
    # File upload
    project_file = models.FileField(
        upload_to='django_projects/',
        help_text="Upload your Django project as a ZIP file"
    )
    
    # Configuration
    python_version = models.CharField(
        max_length=5,
        choices=PYTHON_VERSION_CHOICES,
        default='3.9',
        help_text="Python version to use"
    )
    
    # Domain settings
    subdomain = models.CharField(max_length=100, unique=True)
    custom_domain = models.CharField(
        max_length=200, 
        blank=True, 
        null=True,
        help_text="Optional: Use your own domain (e.g., myapp.com)"
    )
    domain_name = models.CharField(max_length=200, blank=True, null=True)
    
    # Deployment info
    project_folder = models.CharField(max_length=500, blank=True, null=True)
    deployment_status = models.CharField(
        max_length=20,
        choices=DEPLOYMENT_STATUS_CHOICES,
        default='pending'
    )
    
    # Status
    is_active = models.BooleanField(default=False)
    
    # Database configuration
    database_url = models.CharField(max_length=500, blank=True, null=True)
    
    # Resource limits
    memory_limit = models.CharField(
        max_length=10,
        default='512m',
        help_text="Memory limit (e.g., 512m, 1g)"
    )
    
    # Environment variables (JSON field for additional env vars)
    environment_vars = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional environment variables"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_deployed = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.project_name}"

    def get_site_url(self):
        """Get the full URL where the Django project is accessible"""
        if self.domain_name:
            return f"http://{self.domain_name}"
        return None

    def get_admin_url(self):
        """Get Django admin URL"""
        if self.domain_name:
            return f"http://{self.domain_name}/admin/"
        return None

    def get_container_name(self):
        """Get Docker container name"""
        safe_name = "".join(c if c.isalnum() else "_" for c in self.project_name)
        return f"web_{self.user.username}_{safe_name}"

    def get_db_container_name(self):
        """Get database container name"""
        safe_name = "".join(c if c.isalnum() else "_" for c in self.project_name)
        return f"db_{self.user.username}_{safe_name}"

    def delete(self, *args, **kwargs):
        """Override delete to clean up files and deployment"""
        # Clean up uploaded file
        if self.project_file and os.path.exists(self.project_file.path):
            os.remove(self.project_file.path)
        
        # Clean up extracted folder
        if self.project_folder and os.path.exists(self.project_folder):
            import shutil
            shutil.rmtree(self.project_folder, ignore_errors=True)
        
        super().delete(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Django Project"
        verbose_name_plural = "Django Projects"


class DeploymentLog(models.Model):
    """Store deployment logs and history"""
    
    LOG_TYPE_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('success', 'Success'),
    ]

    # Related to either static website or Django project
    website = models.ForeignKey(
        Website, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    django_project = models.ForeignKey(
        DjangoProject, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Log details
    log_type = models.CharField(max_length=10, choices=LOG_TYPE_CHOICES)
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        project_name = self.website.title if self.website else self.django_project.project_name
        return f"{self.user.username} - {project_name} - {self.log_type}"

    class Meta:
        ordering = ['-created_at']


class ServerResource(models.Model):
    """Track server resource usage"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Resource usage
    cpu_usage = models.FloatField(default=0.0)  # Percentage
    memory_usage = models.FloatField(default=0.0)  # MB
    disk_usage = models.FloatField(default=0.0)  # MB
    bandwidth_usage = models.FloatField(default=0.0)  # MB
    
    # Limits
    memory_limit = models.FloatField(default=512.0)  # MB
    disk_limit = models.FloatField(default=1024.0)  # MB
    bandwidth_limit = models.FloatField(default=10240.0)  # MB per month
    
    # Counts
    active_websites = models.IntegerField(default=0)
    active_django_projects = models.IntegerField(default=0)
    
    # Timestamp
    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - Resources at {self.recorded_at}"

    def is_over_limit(self):
        """Check if user is over any resource limits"""
        return (
            self.memory_usage > self.memory_limit or
            self.disk_usage > self.disk_limit or
            self.bandwidth_usage > self.bandwidth_limit
        )

    class Meta:
        ordering = ['-recorded_at']


class DatabaseBackup(models.Model):
    """Database backup information for Django projects"""
    
    django_project = models.ForeignKey(DjangoProject, on_delete=models.CASCADE)
    
    # Backup details
    backup_file = models.FileField(upload_to='backups/')
    backup_size = models.FloatField(help_text="Size in MB")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    is_automatic = models.BooleanField(default=True)
    
    def __str__(self):
        return f"Backup - {self.django_project.project_name} - {self.created_at}"

    class Meta:
        ordering = ['-created_at']


class SSLCertificate(models.Model):
    """SSL certificate management"""
    
    # Can be for either static websites or Django projects
    website = models.ForeignKey(Website, on_delete=models.CASCADE, null=True, blank=True)
    django_project = models.ForeignKey(DjangoProject, on_delete=models.CASCADE, null=True, blank=True)
    
    domain = models.CharField(max_length=200)
    
    # Certificate details
    issued_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    
    # Certificate files (paths)
    cert_file_path = models.CharField(max_length=500, blank=True)
    key_file_path = models.CharField(max_length=500, blank=True)
    
    # Auto-renewal
    auto_renew = models.BooleanField(default=True)
    last_renewal_attempt = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SSL - {self.domain}"

    def is_expiring_soon(self):
        """Check if certificate expires within 30 days"""
        if not self.expires_at:
            return False
        
        from django.utils import timezone
        from datetime import timedelta
        
        return self.expires_at <= timezone.now() + timedelta(days=30)

    class Meta:
        ordering = ['-created_at']


############Github Integration Models##############
from django.db import models
from django.conf import settings

MAIN_DOMAIN = getattr(settings, 'MAIN_DOMAIN', 'samitchaudhary.com.np')


class DeployedProject(models.Model):
    name = models.CharField(max_length=255, unique=True)
    repo_url = models.URLField()
    port = models.PositiveIntegerField(unique=True)
    running = models.BooleanField(default=False)
    pid = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['port']),
            models.Index(fields=['pid']),
            models.Index(fields=['name']),
        ]

    def get_subdomain_url(self):
        """
        Get the subdomain URL for this project.
        Example: myproject.samitchaudhary.com.np
        """
        return f"http://{self.name}.{MAIN_DOMAIN}"
    
    def get_subdomain_url_secure(self):
        """
        Get the HTTPS subdomain URL for this project.
        Example: https://myproject.samitchaudhary.com.np
        """
        return f"https://{self.name}.{MAIN_DOMAIN}"

    def get_host_url(self, request=None):
        """
        Generate the URL to access this deployed project.
        Returns subdomain URL by default.
        """
        # Check if HTTPS is configured
        use_https = getattr(settings, 'USE_HTTPS', False)
        
        if use_https:
            return self.get_subdomain_url_secure()
        return self.get_subdomain_url()

    @property
    def host_url(self):
        """Property for template access without request"""
        return self.get_host_url()
    
    @property
    def subdomain(self):
        """Get just the subdomain part"""
        return f"{self.name}.{MAIN_DOMAIN}"

    def __str__(self):
        return f"{self.name} ({self.subdomain})"