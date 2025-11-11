from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Website, DjangoProject
import zipfile
import os

class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class WebsiteForm(forms.ModelForm):
    """Form for static website deployment"""
    
    class Meta:
        model = Website
        fields = ['title', 'uploaded_file', 'custom_domain']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter website name'
            }),
            'uploaded_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.zip'
            }),
            'custom_domain': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'your-domain.com (optional)'
            }),
        }

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data.get('uploaded_file')
        
        if uploaded_file:
            # Check file extension
            if not uploaded_file.name.lower().endswith('.zip'):
                raise forms.ValidationError("Please upload a ZIP file.")
            
            # Check file size (50MB limit)
            if uploaded_file.size > 50 * 1024 * 1024:
                raise forms.ValidationError("File size cannot exceed 50MB.")
            
            # Reset file pointer to beginning
            uploaded_file.seek(0)
            
            # Validate ZIP file structure
            try:
                with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
                    file_list = zip_ref.namelist()
                    
                    # Check for index file
                    has_index = any(
                        f.lower().endswith(('index.html', 'index.htm')) 
                        for f in file_list
                    )
                    
                    if not has_index:
                        raise forms.ValidationError(
                            "ZIP file must contain an index.html or index.htm file."
                        )
            except zipfile.BadZipFile:
                raise forms.ValidationError("Invalid ZIP file.")
            except Exception as e:
                raise forms.ValidationError(f"Error reading ZIP file: {str(e)}")
            finally:
                # Always reset file pointer
                uploaded_file.seek(0)
        
        return uploaded_file

    def clean_custom_domain(self):
        custom_domain = self.cleaned_data.get('custom_domain')
        
        if custom_domain:
            # Basic domain validation
            import re
            domain_pattern = re.compile(
                r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
                r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
            )
            
            if not domain_pattern.match(custom_domain):
                raise forms.ValidationError("Please enter a valid domain name.")
        
        return custom_domain


class DjangoProjectForm(forms.ModelForm):
    """Form for Django project deployment"""
    
    class Meta:
        model = DjangoProject
        fields = [
            'project_name', 
            'description', 
            'project_file', 
            'python_version',
            'custom_domain',
            'memory_limit',
            'environment_vars'
        ]
        widgets = {
            'project_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter project name',
                'required': True
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Brief description of your Django project'
            }),
            'project_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.zip',
                'required': True
            }),
            'python_version': forms.Select(attrs={
                'class': 'form-control'
            }),
            'custom_domain': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'your-domain.com (optional)'
            }),
            'memory_limit': forms.Select(choices=[
                ('256m', '256 MB'),
                ('512m', '512 MB'),
                ('1g', '1 GB'),
                ('2g', '2 GB'),
            ], attrs={
                'class': 'form-control'
            }),
            'environment_vars': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'KEY1=value1\nKEY2=value2\n(optional)'
            }),
        }

    def clean_project_file(self):
        project_file = self.cleaned_data.get('project_file')
        
        if not project_file:
            raise forms.ValidationError("Please select a project file to upload.")
        
        # Check file extension
        if not project_file.name.lower().endswith('.zip'):
            raise forms.ValidationError("Please upload a ZIP file.")
        
        # Check file size (100MB limit for Django projects)
        max_size = 100 * 1024 * 1024  # 100MB
        if project_file.size > max_size:
            raise forms.ValidationError("File size cannot exceed 100MB.")
        
        # Reset file pointer to beginning
        project_file.seek(0)
        
        # Validate Django project structure
        try:
            with zipfile.ZipFile(project_file, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                
                # Check for manage.py
                has_manage_py = any(
                    f.lower().endswith('manage.py') and not f.startswith('__MACOSX')
                    for f in file_list
                )
                
                if not has_manage_py:
                    raise forms.ValidationError(
                        "ZIP file must contain a Django project with manage.py file."
                    )
                
                # Check for settings.py (more flexible check)
                has_settings = any(
                    'settings.py' in f.lower() and not f.startswith('__MACOSX')
                    for f in file_list
                )
                
                if not has_settings:
                    raise forms.ValidationError(
                        "ZIP file must contain a Django project with settings.py file."
                    )
                    
        except zipfile.BadZipFile:
            raise forms.ValidationError("Invalid or corrupted ZIP file.")
        except Exception as e:
            if "ZIP file must contain" in str(e):
                raise e  # Re-raise our validation errors
            else:
                raise forms.ValidationError(f"Error reading ZIP file: {str(e)}")
        finally:
            # Always reset file pointer for Django to save it
            project_file.seek(0)
        
        return project_file

def clean_project_name(self):
    project_name = self.cleaned_data.get('project_name')
    
    if not project_name:
        raise forms.ValidationError("Project name is required.")
    
    # Strip whitespace
    project_name = project_name.strip()
    
    if len(project_name) < 3:
        raise forms.ValidationError("Project name must be at least 3 characters long.")
    
    if len(project_name) > 50:
        raise forms.ValidationError("Project name cannot exceed 50 characters.")
    
    # Check for valid project name characters
    import re
    if not re.match(r'^[a-zA-Z0-9_\-\s]+$', project_name):
        raise forms.ValidationError(
            "Project name can only contain letters, numbers, spaces, hyphens, and underscores."
        )
    
    return project_name


    def clean_custom_domain(self):
        custom_domain = self.cleaned_data.get('custom_domain')
        
        if custom_domain:
            # Remove protocol if provided
            custom_domain = custom_domain.replace('http://', '').replace('https://', '')
            custom_domain = custom_domain.replace('www.', '').strip()
            
            # Basic domain validation
            import re
            domain_pattern = re.compile(
                r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
                r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
            )
            
            if not domain_pattern.match(custom_domain):
                raise forms.ValidationError("Please enter a valid domain name.")
        
        return custom_domain

    def clean_environment_vars(self):
        env_vars = self.cleaned_data.get('environment_vars')
        
        if env_vars and isinstance(env_vars, str):
            env_vars = env_vars.strip()
            if not env_vars:
                return {}
            
            # Parse environment variables from text format
            env_dict = {}
            for line in env_vars.split('\n'):
                line = line.strip()
                if line and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Validate key format
                    import re
                    if not re.match(r'^[A-Z_][A-Z0-9_]*$', key):
                        raise forms.ValidationError(
                            f"Invalid environment variable name: {key}. "
                            "Use uppercase letters, numbers, and underscores only."
                        )
                    
                    env_dict[key] = value
                elif line:  # Non-empty line without '='
                    raise forms.ValidationError(
                        f"Invalid environment variable format: {line}. "
                        "Use KEY=value format."
                    )
            
            return env_dict
        
        return env_vars if env_vars else {}


class ProjectSettingsForm(forms.ModelForm):
    """Form for updating Django project settings"""
    
    class Meta:
        model = DjangoProject
        fields = [
            'description',
            'custom_domain',
            'memory_limit',
            'environment_vars'
        ]
        widgets = {
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3
            }),
            'custom_domain': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'memory_limit': forms.Select(choices=[
                ('256m', '256 MB'),
                ('512m', '512 MB'),
                ('1g', '1 GB'),
                ('2g', '2 GB'),
            ], attrs={
                'class': 'form-control'
            }),
            'environment_vars': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Convert environment_vars dict to string for display
        if self.instance and self.instance.environment_vars:
            env_string = '\n'.join([
                f"{key}={value}" 
                for key, value in self.instance.environment_vars.items()
            ])
            self.fields['environment_vars'].initial = env_string


class DatabaseRestoreForm(forms.Form):
    """Form for database restore from backup"""
    
    backup_file = forms.FileField(
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.sql,.dump'
        }),
        help_text="Upload a database backup file (.sql or .dump)"
    )
    
    confirm_restore = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label="I understand this will overwrite the current database"
    )

    def clean_backup_file(self):
        backup_file = self.cleaned_data.get('backup_file')
        
        if backup_file:
            # Check file extension
            allowed_extensions = ['.sql', '.dump']
            file_extension = os.path.splitext(backup_file.name)[1].lower()
            
            if file_extension not in allowed_extensions:
                raise forms.ValidationError(
                    "Please upload a .sql or .dump file."
                )
            
            # Check file size (500MB limit)
            if backup_file.size > 500 * 1024 * 1024:
                raise forms.ValidationError("Backup file cannot exceed 500MB.")
            
            # Reset file pointer
            backup_file.seek(0)
        
        return backup_file


class DomainForm(forms.Form):
    """Form for adding custom domain"""
    
    domain = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'example.com'
        })
    )
    
    setup_ssl = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label="Setup SSL certificate automatically"
    )

    def clean_domain(self):
        domain = self.cleaned_data.get('domain')
        
        if domain:
            # Remove protocol if provided
            domain = domain.replace('http://', '').replace('https://', '')
            domain = domain.replace('www.', '').strip()
            
            # Basic domain validation
            import re
            domain_pattern = re.compile(
                r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
                r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
            )
            
            if not domain_pattern.match(domain):
                raise forms.ValidationError("Please enter a valid domain name.")
        
        return domain
    

    ##########################storage######################
from django import forms
from .models import UserFile, PaymentRequest

class FileUploadForm(forms.ModelForm):
    class Meta:
        model = UserFile
        fields = ['title', 'file']

    def clean_file(self):
        file = self.cleaned_data.get('file')
        max_upload_size = 500 * 1024 * 1024  # 500 MB
        if file and file.size > max_upload_size:
            raise forms.ValidationError("File size cannot exceed 500 MB.")
        return file

class PaymentRequestForm(forms.ModelForm):
    GB_CHOICES = [(i, f'{i} GB') for i in range(1, 51)]

    gb_requested = forms.ChoiceField(
        choices=GB_CHOICES,
        widget=forms.Select(attrs={'required': True})
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional notes...'})
    )

    payment_proof = forms.ImageField(required=True)

    class Meta:
        model = PaymentRequest
        fields = ['gb_requested', 'payment_proof', 'notes']

    def clean_gb_requested(self):
        return float(self.cleaned_data['gb_requested'])


#########################Github Deployment######################
from django import forms
from django.core.validators import URLValidator
import re


class DeployForm(forms.Form):
    repo_url = forms.URLField(
        label="GitHub Repository URL",
        max_length=500,
        widget=forms.URLInput(attrs={
            'placeholder': 'https://github.com/username/repository',
            'class': 'form-control'
        }),
        help_text="Enter a valid GitHub HTTPS URL (e.g., https://github.com/user/repo). "
                  "The project will be deployed at projectname.samitchaudhary.com.np"
    )

    def clean_repo_url(self):
        """Validate that URL is a valid GitHub repository"""
        url = self.cleaned_data['repo_url'].strip()
        
        # Must be HTTPS GitHub URL
        github_pattern = r'^https://github\.com/[\w-]+/[\w.-]+(?:\.git)?$'
        if not re.match(github_pattern, url):
            raise forms.ValidationError(
                "Invalid GitHub URL. Must be in format: https://github.com/username/repository"
            )
        
        # Extract project name and validate it's suitable for subdomain
        project_name = url.rstrip("/").split("/")[-1].replace(".git", "")
        
        # Subdomain validation - must be DNS-safe
        subdomain_pattern = r'^[a-zA-Z][a-zA-Z0-9-]{0,50}$'
        if not re.match(subdomain_pattern, project_name):
            raise forms.ValidationError(
                f"Project name '{project_name}' is not suitable for subdomain. "
                "Must start with a letter and contain only letters, numbers, and hyphens."
            )
        
        # Check for reserved subdomains
        reserved_subdomains = [
            'www', 'mail', 'ftp', 'smtp', 'pop', 'imap',
            'admin', 'api', 'app', 'blog', 'dev', 'test',
            'staging', 'production', 'cdn', 'static', 'assets'
        ]
        
        if project_name.lower() in reserved_subdomains:
            raise forms.ValidationError(
                f"Project name '{project_name}' is reserved. Please choose a different repository name."
            )
        
        return url