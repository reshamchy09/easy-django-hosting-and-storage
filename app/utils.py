import os
import subprocess
import zipfile
import logging
import json
import shutil
import platform
import socket
import signal
import time
import sys
import re
from django.conf import settings
from pathlib import Path

logger = logging.getLogger(__name__)

# Detect operating system
IS_WINDOWS = platform.system() == 'Windows'
MEDIA_ROOT = getattr(settings, 'WEBSITES_ROOT', os.path.join(settings.MEDIA_ROOT, "websites"))

def get_local_ip():
    """
    Get the local IP address of the server
    """
    try:
        # Create a socket and connect to an external address
        # This doesn't actually send data, just determines the local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        logger.warning(f"Could not detect local IP: {str(e)}")
        # Fallback to localhost
        return "127.0.0.1"

def deploy_django_project(username, project_name, uploaded_file_path, custom_domain=None):
    """
    Deploy Django project with subdomain support
    """
    try:
        python_cmd = sys.executable
        logger.info(f"Using Python executable: {python_cmd}")
        
        # Create safe project name
        safe_name = "".join(c if c.isalnum() else "_" for c in project_name)
        project_folder = os.path.join(MEDIA_ROOT, f"{username}_{safe_name}")
        
        logger.info(f"Starting Django deployment for {username}_{safe_name}")
        
        # Clean up existing deployment
        if os.path.exists(project_folder):
            stop_django_project(username, safe_name)
            shutil.rmtree(project_folder, ignore_errors=True)
        os.makedirs(project_folder, exist_ok=True)

        # Extract uploaded Django project
        logger.info(f"Extracting project from {uploaded_file_path}")
        with zipfile.ZipFile(uploaded_file_path, 'r') as zip_ref:
            zip_ref.extractall(project_folder)

        # Detect Django project structure
        django_info = detect_django_structure(project_folder)
        if not django_info['is_django']:
            return {'success': False, 'error': 'Not a valid Django project - missing manage.py or settings.py'}

        # Get local IP address
        local_ip = get_local_ip()
        
        # Generate subdomain - use custom domain if provided
        # Format: projectname.samitchaudhary.com.np
        BASE_DOMAIN = "samitchaudhary.com.np"
        
        if custom_domain:
            domain_name = custom_domain
        else:
            # Create subdomain from project name
            subdomain = safe_name.lower().replace('_', '-')
            domain_name = f"{subdomain}.{BASE_DOMAIN}"
        
        logger.info(f"Using domain: {domain_name}")

        # Deploy without virtual environment
        success, port, error_msg = deploy_django_no_venv(
            username, safe_name, project_folder, django_info, 
            domain_name, python_cmd, local_ip
        )
        
        if success:
            logger.info(f"Successfully deployed Django project on {domain_name}")
            return {
                'success': True, 
                'domain_name': domain_name, 
                'port': port, 
                'ip': local_ip,
                'full_url': f"http://{domain_name}"
            }
        else:
            return {'success': False, 'error': error_msg or 'Django deployment failed'}

    except Exception as e:
        logger.error(f"Django deployment error: {str(e)}")
        return {'success': False, 'error': str(e)}


def deploy_django_no_venv(username, project_name, project_folder, django_info, domain_name, python_cmd, local_ip):
    """
    Deploy Django project without virtual environment (updated with Nginx)
    """
    try:
        logger.info(f"Starting deployment without virtual environment for {username}_{project_name}")
        
        # Find available port
        available_port = find_available_port(8000)
        
        # Install project dependencies first
        install_success = install_project_requirements(project_folder, python_cmd)
        if not install_success:
            logger.warning("Some dependencies might not have been installed, but continuing...")
        
        # Configure Django settings for SQLite with subdomain
        success = configure_django_settings_simple(project_folder, django_info, domain_name, available_port, local_ip)
        if not success:
            return False, None, "Failed to configure Django settings"
        
        # Run database migrations
        run_django_migrations_direct(project_folder, django_info, python_cmd)
        
        # Start Django development server on localhost (not 0.0.0.0)
        # Nginx will handle external requests
        success = start_django_server_direct(username, project_name, project_folder, django_info, available_port, python_cmd, '127.0.0.1')
        
        if success:
            # Generate Nginx configuration for subdomain
            subdomain = domain_name.replace(f".{BASE_DOMAIN}", "")
            nginx_success = generate_nginx_config(subdomain, available_port, username, project_name)
            
            if not nginx_success:
                logger.warning("Nginx configuration failed, but Django server is running")
            
            return True, available_port, None
        else:
            return False, None, "Failed to start Django server"

    except Exception as e:
        logger.error(f"Deployment error: {str(e)}")
        return False, None, str(e)

def is_in_virtualenv():
    """Check if we're running in a virtual environment"""
    return (hasattr(sys, 'real_prefix') or 
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))

def install_project_requirements(project_folder, python_cmd):
    """
    Install project requirements from requirements.txt or analyze imports
    """
    try:
        logger.info("Installing project requirements")
        
        # First install essential Django packages
        install_minimal_requirements(python_cmd)
        
        # Look for requirements.txt
        requirements_file = None
        for root, dirs, files in os.walk(project_folder):
            for file in files:
                if file.lower() in ['requirements.txt', 'requirements-dev.txt', 'requirements-base.txt']:
                    requirements_file = os.path.join(root, file)
                    break
            if requirements_file:
                break
        
        if requirements_file:
            logger.info(f"Found requirements file: {requirements_file}")
            return install_from_requirements_file(requirements_file, python_cmd)
        else:
            logger.info("No requirements.txt found, analyzing imports")
            return install_from_import_analysis(project_folder, python_cmd)
    
    except Exception as e:
        logger.error(f"Requirements installation error: {str(e)}")
        return False

def get_pip_install_args(python_cmd):
    """Get appropriate pip install arguments based on environment"""
    base_args = [python_cmd, '-m', 'pip', 'install']
    
    # Check if we're in a virtual environment
    if is_in_virtualenv():
        logger.info("Running in virtual environment - using standard pip install")
        return base_args + ['--quiet']
    else:
        logger.info("Not in virtual environment - using --user flag")
        return base_args + ['--user', '--quiet']

def install_from_requirements_file(requirements_file, python_cmd):
    """
    Install packages from requirements.txt
    """
    try:
        # Read and filter requirements
        with open(requirements_file, 'r', encoding='utf-8') as f:
            requirements = f.readlines()
        
        # Filter out problematic packages and comments
        safe_requirements = []
        for req in requirements:
            req = req.strip()
            if not req or req.startswith('#') or req.startswith('-'):
                continue
            
            # Skip packages that are likely to cause issues
            req_lower = req.lower()
            if any(skip in req_lower for skip in ['psycopg', 'mysql', 'oracle', 'pywin32']):
                logger.info(f"Skipping potentially problematic package: {req}")
                continue
            
            safe_requirements.append(req)
        
        if not safe_requirements:
            return True
        
        # Get appropriate pip install command
        pip_args = get_pip_install_args(python_cmd)
        
        # Try installing all requirements at once first
        try:
            logger.info("Attempting bulk installation of requirements")
            # Create temporary requirements file with safe requirements
            temp_req_file = requirements_file + '.safe'
            with open(temp_req_file, 'w') as f:
                f.write('\n'.join(safe_requirements))
            
            result = subprocess.run(
                pip_args + ['-r', temp_req_file],
                capture_output=True, text=True, timeout=300
            )
            
            os.remove(temp_req_file)
            
            if result.returncode == 0:
                logger.info("Bulk installation successful")
                return True
            else:
                logger.warning(f"Bulk installation failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"Bulk installation error: {str(e)}")
        
        # Fall back to individual package installation
        logger.info("Falling back to individual package installation")
        for req in safe_requirements:
            try:
                logger.info(f"Installing: {req}")
                result = subprocess.run(
                    pip_args + [req], 
                    capture_output=True, text=True, timeout=180
                )
                
                if result.returncode != 0:
                    logger.warning(f"Failed to install {req}: {result.stderr}")
                else:
                    logger.info(f"Successfully installed {req}")
                    
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout installing {req}")
            except Exception as e:
                logger.warning(f"Error installing {req}: {str(e)}")
        
        return True
        
    except Exception as e:
        logger.error(f"Requirements file installation error: {str(e)}")
        return False

def install_from_import_analysis(project_folder, python_cmd):
    """
    Analyze Python files for imports and install missing packages
    """
    try:
        # Common package mappings
        package_mappings = {
            'xlsxwriter': 'XlsxWriter',
            'openpyxl': 'openpyxl',
            'pandas': 'pandas',
            'numpy': 'numpy',
            'requests': 'requests',
            'pillow': 'Pillow',
            'pil': 'Pillow',
            'rest_framework': 'djangorestframework',
            'corsheaders': 'django-cors-headers',
            'crispy_forms': 'django-crispy-forms',
            'debug_toolbar': 'django-debug-toolbar',
            'celery': 'celery',
            'redis': 'redis',
            'boto3': 'boto3',
            'reportlab': 'reportlab',
        }
        
        # Python standard library modules (DO NOT try to install these)
        stdlib_modules = {
            # Built-in modules
            'abc', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio', 'asyncore',
            'atexit', 'audioop', 'base64', 'bdb', 'binascii', 'binhex', 'bisect', 'builtins',
            'bz2', 'calendar', 'cgi', 'cgitb', 'chunk', 'cmath', 'cmd', 'code', 'codecs',
            'codeop', 'collections', 'colorsys', 'compileall', 'concurrent', 'configparser',
            'contextlib', 'contextvars', 'copy', 'copyreg', 'crypt', 'csv', 'ctypes',
            'curses', 'dataclasses', 'datetime', 'dbm', 'decimal', 'difflib', 'dis',
            'distutils', 'doctest', 'email', 'encodings', 'enum', 'errno', 'faulthandler',
            'fcntl', 'filecmp', 'fileinput', 'fnmatch', 'formatter', 'fractions', 'ftplib',
            'functools', 'gc', 'getopt', 'getpass', 'gettext', 'glob', 'graphlib', 'grp',
            'gzip', 'hashlib', 'heapq', 'hmac', 'html', 'http', 'imaplib', 'imghdr', 'imp',
            'importlib', 'inspect', 'io', 'ipaddress', 'itertools', 'json', 'keyword',
            'lib2to3', 'linecache', 'locale', 'logging', 'lzma', 'mailbox', 'mailcap',
            'marshal', 'math', 'mimetypes', 'mmap', 'modulefinder', 'msilib', 'msvcrt',
            'multiprocessing', 'netrc', 'nis', 'nntplib', 'numbers', 'operator', 'optparse',
            'os', 'ossaudiodev', 'parser', 'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes',
            'pkgutil', 'platform', 'plistlib', 'poplib', 'posix', 'posixpath', 'pprint',
            'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr', 'pydoc', 'queue',
            'quopri', 'random', 're', 'readline', 'reprlib', 'resource', 'rlcompleter',
            'runpy', 'sched', 'secrets', 'select', 'selectors', 'shelve', 'shlex', 'shutil',
            'signal', 'site', 'smtpd', 'smtplib', 'sndhdr', 'socket', 'socketserver',
            'spwd', 'sqlite3', 'ssl', 'stat', 'statistics', 'string', 'stringprep', 'struct',
            'subprocess', 'sunau', 'symbol', 'symtable', 'sys', 'sysconfig', 'syslog',
            'tabnanny', 'tarfile', 'telnetlib', 'tempfile', 'termios', 'test', 'textwrap',
            'threading', 'time', 'timeit', 'tkinter', 'token', 'tokenize', 'trace',
            'traceback', 'tracemalloc', 'tty', 'turtle', 'turtledemo', 'types', 'typing',
            'unicodedata', 'unittest', 'urllib', 'uu', 'uuid', 'venv', 'warnings', 'wave',
            'weakref', 'webbrowser', 'winreg', 'winsound', 'wsgiref', 'xdrlib', 'xml',
            'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib',
            # Django modules (already installed)
            'django',
        }
        
        # Find all Python files and extract imports
        imports = set()
        for root, dirs, files in os.walk(project_folder):
            # Skip certain directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'migrations']]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            # Extract import statements
                            import_matches = re.findall(r'^(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)', content, re.MULTILINE)
                            imports.update(import_matches)
                    except Exception as e:
                        logger.warning(f"Error reading {file_path}: {str(e)}")
        
        # Filter and install packages
        packages_to_install = []
        for imp in imports:
            imp_lower = imp.lower()
            
            # Skip standard library modules
            if imp_lower in stdlib_modules:
                continue
            
            # Check if there's a package mapping
            if imp_lower in package_mappings:
                packages_to_install.append(package_mappings[imp_lower])
            else:
                # Only add if it's not a known stdlib module
                # This is a safe fallback for third-party packages
                packages_to_install.append(imp)
        
        # Remove duplicates
        packages_to_install = list(set(packages_to_install))
        
        if not packages_to_install:
            logger.info("No external packages detected to install")
            return True
        
        logger.info(f"Detected packages to install: {packages_to_install}")
        
        # Get appropriate pip install command
        pip_args = get_pip_install_args(python_cmd)
        
        # Install packages
        for package in packages_to_install:
            try:
                logger.info(f"Installing detected package: {package}")
                result = subprocess.run(
                    pip_args + [package], 
                    capture_output=True, text=True, timeout=120
                )
                
                if result.returncode == 0:
                    logger.info(f"Successfully installed {package}")
                else:
                    logger.warning(f"Failed to install {package}: {result.stderr}")
                    
            except Exception as e:
                logger.warning(f"Error installing {package}: {str(e)}")
        
        return True
        
    except Exception as e:
        logger.error(f"Import analysis error: {str(e)}")
        return False

def install_minimal_requirements(python_cmd):
    """
    Install only the most essential packages
    """
    try:
        logger.info("Installing minimal Django requirements")
        
        # Only install Django and whitenoise if not already available
        essential_packages = ['Django', 'whitenoise']
        
        # Get appropriate pip install command
        pip_args = get_pip_install_args(python_cmd)
        
        for package in essential_packages:
            try:
                # Check if package is already available
                check_result = subprocess.run([
                    python_cmd, '-c', f'import {package.lower()}'
                ], capture_output=True, timeout=5)
                
                if check_result.returncode == 0:
                    logger.info(f"{package} is already available")
                    continue
                
                # Install package
                install_result = subprocess.run(
                    pip_args + [package], 
                    capture_output=True, text=True, timeout=120
                )
                
                if install_result.returncode == 0:
                    logger.info(f"Successfully installed {package}")
                else:
                    logger.warning(f"Failed to install {package}: {install_result.stderr}")
                    
            except Exception as e:
                logger.warning(f"Error with {package}: {str(e)}")
        
        return True
        
    except Exception as e:
        logger.error(f"Requirements installation error: {str(e)}")
        return False

def configure_django_settings_simple(project_folder, django_info, domain_name, port, local_ip):
    """
    Simple Django settings configuration with subdomain support
    """
    try:
        # Find settings.py file
        settings_file_path = find_settings_file(project_folder, django_info)
        if not settings_file_path:
            logger.error("Could not find settings.py file")
            return False
        
        # Read and modify settings
        with open(settings_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Create backup
        backup_path = settings_file_path + '.backup'
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Try to modify existing settings first
        modified_content = modify_existing_settings(content, project_folder, domain_name, port, local_ip)
        
        # If modification failed, create simple settings
        if not modified_content:
            modified_content = create_simple_settings(content, project_folder, domain_name, port, django_info, local_ip)
        
        # Write modified settings
        with open(settings_file_path, 'w', encoding='utf-8') as f:
            f.write(modified_content)
        
        logger.info("Django settings configured")
        return True
        
    except Exception as e:
        logger.error(f"Settings configuration error: {str(e)}")
        return False


def modify_existing_settings(content, project_folder, domain_name, port, local_ip):
    """
    Try to modify existing settings with subdomain support
    """
    try:
        lines = content.split('\n')
        modified_lines = []
        db_path = os.path.join(project_folder, 'db.sqlite3').replace('\\', '/')
        skip_until_end = False
        brace_count = 0
        
        for line in lines:
            original_line = line
            
            # Handle skipping multi-line DATABASES configuration
            if skip_until_end:
                if '{' in line:
                    brace_count += line.count('{')
                if '}' in line:
                    brace_count -= line.count('}')
                    if brace_count <= 0:
                        skip_until_end = False
                        brace_count = 0
                continue
            
            # Modify DATABASES setting to use SQLite
            if 'DATABASES' in line and '=' in line and not line.strip().startswith('#'):
                modified_lines.append("# Modified DATABASES setting for SQLite")
                modified_lines.append("DATABASES = {")
                modified_lines.append("    'default': {")
                modified_lines.append("        'ENGINE': 'django.db.backends.sqlite3',")
                modified_lines.append(f"        'NAME': r'{db_path}',")
                modified_lines.append("    }")
                modified_lines.append("}")
                
                # Check if this is a multi-line DATABASES block
                if '{' in line:
                    skip_until_end = True
                    brace_count = line.count('{') - line.count('}')
                continue
            
            # Modify ALLOWED_HOSTS with subdomain
            elif line.strip().startswith('ALLOWED_HOSTS') and not line.strip().startswith('#'):
                allowed_hosts = [
                    'localhost', 
                    '127.0.0.1', 
                    '0.0.0.0', 
                    local_ip,
                    domain_name,
                    f'.{domain_name.split(".", 1)[1] if "." in domain_name else domain_name}',  # Wildcard subdomain
                    '*.samitchaudhary.com.np',
                    'samitchaudhary.com.np'
                ]
                modified_lines.append(f"ALLOWED_HOSTS = {allowed_hosts}")
                continue
            
            # Modify DEBUG setting
            elif line.strip().startswith('DEBUG') and '=' in line and not line.strip().startswith('#'):
                modified_lines.append("DEBUG = True")
                continue
            
            # Add whitenoise to MIDDLEWARE if not present
            elif 'MIDDLEWARE' in line and '=' in line and 'whitenoise' not in content.lower() and not line.strip().startswith('#'):
                modified_lines.append("# Modified MIDDLEWARE to include WhiteNoise")
                modified_lines.append("MIDDLEWARE = [")
                modified_lines.append("    'django.middleware.security.SecurityMiddleware',")
                modified_lines.append("    'whitenoise.middleware.WhiteNoiseMiddleware',")
                modified_lines.append("    'django.contrib.sessions.middleware.SessionMiddleware',")
                modified_lines.append("    'django.middleware.common.CommonMiddleware',")
                modified_lines.append("    'django.middleware.csrf.CsrfViewMiddleware',")
                modified_lines.append("    'django.contrib.auth.middleware.AuthenticationMiddleware',")
                modified_lines.append("    'django.contrib.messages.middleware.MessageMiddleware',")
                modified_lines.append("    'django.middleware.clickjacking.XFrameOptionsMiddleware',")
                modified_lines.append("]")
                
                # Skip original MIDDLEWARE definition
                if '[' in line:
                    skip_until_end = True
                    brace_count = 1
                continue
            
            else:
                modified_lines.append(original_line)
        
        return '\n'.join(modified_lines)
        
    except Exception as e:
        logger.warning(f"Could not modify existing settings: {str(e)}")
        return None

def find_settings_file(project_folder, django_info):
    """
    Find the settings.py file in the project
    """
    # Try the detected settings module path first
    settings_module = django_info.get('settings_module')
    if settings_module:
        settings_parts = settings_module.split('.')
        settings_file_path = os.path.join(project_folder, *settings_parts[:-1], 'settings.py')
        if os.path.exists(settings_file_path):
            return settings_file_path
    
    # Search for settings.py in the project
    for root, dirs, files in os.walk(project_folder):
        if 'settings.py' in files:
            return os.path.join(root, 'settings.py')
    
    return None

def create_simple_settings(original_content, project_folder, domain_name, port, django_info, local_ip):
    """
    Create simple settings configuration with subdomain support
    """
    db_path = os.path.join(project_folder, 'db.sqlite3').replace('\\', '/')
    
    # Extract important settings from original content
    root_urlconf = 'myproject.urls'
    wsgi_application = 'myproject.wsgi.application'
    installed_apps = []
    
    lines = original_content.split('\n')
    in_installed_apps = False
    
    for line in lines:
        line = line.strip()
        
        if line.startswith('ROOT_URLCONF'):
            root_urlconf = line.split('=')[1].strip().strip("'\"")
        elif line.startswith('WSGI_APPLICATION'):
            wsgi_application = line.split('=')[1].strip().strip("'\"")
        elif 'INSTALLED_APPS' in line and '=' in line:
            in_installed_apps = True
        elif in_installed_apps:
            if line.startswith(']') or line.startswith(')'):
                in_installed_apps = False
            elif line and not line.startswith('#'):
                app_name = line.strip().strip("',\"")
                if app_name and not app_name.startswith('django.contrib'):
                    installed_apps.append(app_name)
    
    # Build INSTALLED_APPS
    apps_string = '''INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'whitenoise.runserver_nostatic','''
    
    for app in installed_apps:
        apps_string += f"\n    '{app}',"
    
    apps_string += "\n]"
    
    # Build ALLOWED_HOSTS with subdomain support
    allowed_hosts = [
        'localhost',
        '127.0.0.1',
        '0.0.0.0',
        local_ip,
        domain_name,
        '*.samitchaudhary.com.np',
        'samitchaudhary.com.np'
    ]
    
    # Simple settings template
    simple_settings = f'''# Modified settings for subdomain deployment
import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-temp-key-for-deployment-{hash(project_folder) % 10000}'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = {allowed_hosts}

# Application definition
{apps_string}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = '{root_urlconf}'

TEMPLATES = [
    {{
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {{
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        }},
    }},
]

WSGI_APPLICATION = '{wsgi_application}'

# Database
DATABASES = {{
    'default': {{
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': r'{db_path}',
    }}
}}

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
'''
    
    return simple_settings

def run_django_migrations_direct(project_folder, django_info, python_cmd):
    """
    Run Django migrations directly
    """
    try:
        logger.info("Running Django migrations")
        
        manage_py_path = django_info.get('manage_py_path')
        if not manage_py_path:
            logger.warning("No manage.py found")
            return False
        
        project_root = os.path.dirname(manage_py_path)
        original_dir = os.getcwd()
        
        try:
            os.chdir(project_root)
            
            # Run makemigrations first
            makemigrations_result = subprocess.run([
                python_cmd, 'manage.py', 'makemigrations'
            ], capture_output=True, text=True, timeout=60)
            
            if makemigrations_result.returncode != 0:
                logger.warning(f"Makemigrations issues: {makemigrations_result.stderr}")
            
            # Run migrations
            migrate_result = subprocess.run([
                python_cmd, 'manage.py', 'migrate'
            ], capture_output=True, text=True, timeout=120)
            
            if migrate_result.returncode == 0:
                logger.info("Migrations completed successfully")
            else:
                logger.warning(f"Migration had issues: {migrate_result.stderr}")
            
            # Collect static files
            try:
                collectstatic_result = subprocess.run([
                    python_cmd, 'manage.py', 'collectstatic', '--noinput'
                ], capture_output=True, text=True, timeout=60)
                
                if collectstatic_result.returncode == 0:
                    logger.info("Static files collected successfully")
                else:
                    logger.warning("Static files collection had issues")
            except Exception as e:
                logger.warning(f"Error collecting static files: {str(e)}")
            
            return True
                
        finally:
            os.chdir(original_dir)
            
    except Exception as e:
        logger.warning(f"Migration error: {str(e)}")
        return False

def start_django_server_direct(username, project_name, project_folder, django_info, port, python_cmd, local_ip):
    """
    Start Django server on all interfaces (0.0.0.0) to be accessible via IP
    """
    try:
        logger.info(f"Starting Django server on {local_ip}:{port}")
        
        manage_py_path = django_info.get('manage_py_path')
        if not manage_py_path:
            return False
        
        project_root = os.path.dirname(manage_py_path)
        
        # Create log files for debugging
        log_file = os.path.join(project_folder, f'{username}_{project_name}.log')
        
        # Start server process on 0.0.0.0 to listen on all interfaces
        if IS_WINDOWS:
            process = subprocess.Popen([
                python_cmd, 'manage.py', 'runserver', f'0.0.0.0:{port}', '--noreload'
            ], cwd=project_root, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
               stdout=open(log_file, 'w'), stderr=subprocess.STDOUT)
        else:
            process = subprocess.Popen([
                python_cmd, 'manage.py', 'runserver', f'0.0.0.0:{port}', '--noreload'
            ], cwd=project_root, 
               stdout=open(log_file, 'w'), stderr=subprocess.STDOUT)
        
        # Save PID and port
        pid_file = os.path.join(project_folder, f'{username}_{project_name}.pid')
        with open(pid_file, 'w') as f:
            f.write(str(process.pid))
        
        port_file = os.path.join(project_folder, f'{username}_{project_name}.port')
        with open(port_file, 'w') as f:
            f.write(str(port))
        
        # Save IP address
        ip_file = os.path.join(project_folder, f'{username}_{project_name}.ip')
        with open(ip_file, 'w') as f:
            f.write(local_ip)
        
        # Wait and check
        time.sleep(5)
        
        if process.poll() is None:
            logger.info(f"Django server started successfully on {local_ip}:{port}")
            return True
        else:
            logger.error("Django server failed to start")
            # Log the error for debugging
            try:
                with open(log_file, 'r') as f:
                    log_content = f.read()
                    logger.error(f"Server logs: {log_content}")
            except:
                pass
            return False
        
    except Exception as e:
        logger.error(f"Server start error: {str(e)}")
        return False

def find_available_port(start_port=8000):
    """Find an available port"""
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return port
        except OSError:
            continue
    return start_port

def stop_django_project(username, project_name):
    """Stop Django project"""
    try:
        project_folder = os.path.join(MEDIA_ROOT, f"{username}_{project_name}")
        pid_file = os.path.join(project_folder, f'{username}_{project_name}.pid')
        
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            if IS_WINDOWS:
                subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            
            os.remove(pid_file)
            logger.info(f"Stopped Django server with PID {pid}")
            
    except Exception as e:
        logger.warning(f"Error stopping Django project: {str(e)}")

def detect_django_structure(project_folder):
    """Detect Django project structure"""
    django_info = {
        'is_django': False,
        'manage_py_path': None,
        'settings_module': None,
        'project_root': project_folder
    }

    # Find manage.py
    for root, dirs, files in os.walk(project_folder):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        if 'manage.py' in files:
            django_info['is_django'] = True
            django_info['manage_py_path'] = os.path.join(root, 'manage.py')
            django_info['project_root'] = root
            break

    # Find settings module
    if django_info['is_django']:
        project_root = Path(django_info['project_root'])
        for item in project_root.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                settings_file = item / 'settings.py'
                if settings_file.exists():
                    django_info['settings_module'] = f"{item.name}.settings"
                    break

    return django_info

def check_django_deployment_status(username, project_name, domain_name):
    """Check deployment status"""
    try:
        project_folder = os.path.join(MEDIA_ROOT, f"{username}_{project_name}")
        pid_file = os.path.join(project_folder, f'{username}_{project_name}.pid')
        log_file = os.path.join(project_folder, f'{username}_{project_name}.log')
        
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            try:
                if IS_WINDOWS:
                    result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], 
                                          capture_output=True, text=True)
                    process_running = str(pid) in result.stdout
                else:
                    os.kill(pid, 0)
                    process_running = True
            except (OSError, ProcessLookupError):
                process_running = False
            
            # Get logs if available
            logs = f'Process PID: {pid}'
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r') as f:
                        log_content = f.read()
                        logs = log_content[-1000:] if len(log_content) > 1000 else log_content
                except:
                    pass
            
            return {
                'status': process_running,
                'container_running': process_running,
                'web_accessible': process_running,
                'db_running': True,
                'logs': logs
            }
        else:
            return {'status': False, 'logs': 'Server not running'}

    except Exception as e:
        return {'status': False, 'error': str(e)}

# Update cleanup_django_deployment to remove Nginx config
def cleanup_django_deployment(username, project_name):
    """Cleanup deployment including Nginx configuration"""
    try:
        stop_django_project(username, project_name)
        
        # Remove Nginx configuration
        project_folder = os.path.join(MEDIA_ROOT, f"{username}_{project_name}")
        
        # Try to get subdomain from project
        try:
            from .models import DjangoProject
            project = DjangoProject.objects.filter(
                user__username=username,
                project_name=project_name
            ).first()
            
            if project and project.subdomain:
                subdomain = project.subdomain.replace(f".{BASE_DOMAIN}", "")
                remove_nginx_config(subdomain)
        except:
            pass
        
        if os.path.exists(project_folder):
            shutil.rmtree(project_folder, ignore_errors=True)
            
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")

def get_django_project_info(project_folder):
    """Get project info"""
    return {
        'is_django': True,
        'database_backend': 'SQLite3',
        'static_configured': True,
        'apps': []
    }

# Placeholder functions
def deploy_website(username, title, file_path, is_dynamic=False, custom_domain=None):
    local_ip = get_local_ip()
    return f"{local_ip}:8080"

def check_deployment_status(username, title, domain_name):
    return True

def cleanup_deployment(username, title):
    pass



NGINX_SITES_AVAILABLE = "/etc/nginx/sites-available"
NGINX_SITES_ENABLED = "/etc/nginx/sites-enabled"
BASE_DOMAIN = "samitchaudhary.com.np"

def generate_nginx_config(subdomain, port, username, project_name):
    """
    Generate Nginx configuration for a subdomain
    """
    try:
        config_name = f"{subdomain}"
        config_path = os.path.join(NGINX_SITES_AVAILABLE, config_name)
        
        nginx_config = f"""# Nginx configuration for {subdomain}
# Generated automatically for user: {username}, project: {project_name}

server {{
    listen 80;
    server_name {subdomain}.{BASE_DOMAIN};
    
    # Logging
    access_log /var/log/nginx/{subdomain}_access.log;
    error_log /var/log/nginx/{subdomain}_error.log;
    
    # Proxy settings
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $server_name;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
    
    # Static files (if served by Nginx)
    location /static/ {{
        alias /var/www/{subdomain}/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}
    
    # Media files
    location /media/ {{
        alias /var/www/{subdomain}/media/;
        expires 30d;
    }}
}}
"""
        
        # Write configuration file
        with open(config_path, 'w') as f:
            f.write(nginx_config)
        
        logger.info(f"Nginx config created at {config_path}")
        
        # Create symbolic link to enable the site
        enabled_path = os.path.join(NGINX_SITES_ENABLED, config_name)
        if not os.path.exists(enabled_path):
            os.symlink(config_path, enabled_path)
            logger.info(f"Enabled site: {config_name}")
        
        # Test Nginx configuration
        test_result = subprocess.run(
            ['sudo', 'nginx', '-t'],
            capture_output=True, text=True
        )
        
        if test_result.returncode == 0:
            logger.info("Nginx configuration test passed")
            
            # Reload Nginx
            reload_result = subprocess.run(
                ['sudo', 'systemctl', 'reload', 'nginx'],
                capture_output=True, text=True
            )
            
            if reload_result.returncode == 0:
                logger.info("Nginx reloaded successfully")
                return True
            else:
                logger.error(f"Nginx reload failed: {reload_result.stderr}")
                return False
        else:
            logger.error(f"Nginx config test failed: {test_result.stderr}")
            # Rollback
            os.remove(config_path)
            if os.path.exists(enabled_path):
                os.remove(enabled_path)
            return False
        
    except Exception as e:
        logger.error(f"Error generating Nginx config: {str(e)}")
        return False


def remove_nginx_config(subdomain):
    """
    Remove Nginx configuration for a subdomain
    """
    try:
        config_name = f"{subdomain}"
        config_path = os.path.join(NGINX_SITES_AVAILABLE, config_name)
        enabled_path = os.path.join(NGINX_SITES_ENABLED, config_name)
        
        # Remove symbolic link
        if os.path.exists(enabled_path):
            os.remove(enabled_path)
            logger.info(f"Removed enabled site: {config_name}")
        
        # Remove configuration file
        if os.path.exists(config_path):
            os.remove(config_path)
            logger.info(f"Removed config: {config_path}")
        
        # Reload Nginx
        subprocess.run(
            ['sudo', 'systemctl', 'reload', 'nginx'],
            capture_output=True, text=True
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Error removing Nginx config: {str(e)}")
        return False

