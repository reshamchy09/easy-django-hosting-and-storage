from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .forms import WebsiteForm, SignupForm, DjangoProjectForm
from .models import Website, DjangoProject
from .utils import (
    deploy_django_project, 
    check_django_deployment_status,
    cleanup_django_deployment,
    get_django_project_info,
    get_local_ip
)
from django.conf import settings
from django.http import JsonResponse
import os
import uuid
import logging

logger = logging.getLogger(__name__)

# Existing public pages
def home(request):
    return render(request, 'home.html')

def about(request):
    return render(request, 'about.html')

def plans(request):
    return render(request, 'plans.html')

def contact(request):
    return render(request, 'contact.html')

# Auth
def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if password != confirm_password:
            messages.error(request, "Passwords do not match!")
            return redirect('signup')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken!")
            return redirect('signup')

        user = User.objects.create_user(username=username, email=email, password=password)
        user.save()
        messages.success(request, "Signup successful! Please log in.")
        return redirect('login')

    return render(request, 'signup.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid credentials")
            return redirect('login')
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('home')

# Dashboard
@login_required
def dashboard_view(request):
    # Get both static websites and Django projects
    websites = Website.objects.filter(user=request.user)
    django_projects = DjangoProject.objects.filter(user=request.user)
    
    context = {
        'websites': websites,
        'django_projects': django_projects,
        'total_sites': websites.count() + django_projects.count(),
        'active_sites': websites.filter(is_active=True).count() + django_projects.filter(is_active=True).count()
    }
    
    return render(request, 'dashboard.html', context)

# Django Project Management

@login_required
def deploy_django_view(request):
    """Deploy Django project with subdomain URLs"""
    if request.method == 'POST':
        logger.info(f"POST data received from user {request.user.username}")
        logger.info(f"Files received: {list(request.FILES.keys())}")
        
        form = DjangoProjectForm(request.POST, request.FILES)
        logger.info(f"Form is valid: {form.is_valid()}")
        
        if form.is_valid():
            try:
                # Don't save yet - we need to set subdomain first
                django_project = form.save(commit=False)
                django_project.user = request.user

                # Generate safe project name
                import re
                project_name_cleaned = django_project.project_name.strip()
                safe_name = "".join(c if c.isalnum() else "_" for c in project_name_cleaned)
                
                # Remove consecutive underscores and clean up
                safe_name = re.sub(r'_{2,}', '_', safe_name)
                safe_name = safe_name.strip('_')
                
                if len(safe_name) < 3:
                    safe_name = f"{safe_name}_project"
                
                if len(safe_name) < 3:
                    safe_name = f"user_project_{uuid.uuid4().hex[:6]}"
                
                # Generate subdomain format with uniqueness check
                BASE_DOMAIN = "samitchaudhary.com.np"
                subdomain_base = safe_name.lower().replace('_', '-')
                
                # Start with base subdomain
                subdomain = f"{subdomain_base}.{BASE_DOMAIN}"
                
                # Check if subdomain exists and make it unique
                # IMPORTANT: Check BEFORE assigning to django_project
                counter = 1
                while DjangoProject.objects.filter(subdomain=subdomain).exists():
                    logger.info(f"Subdomain {subdomain} already exists, trying variation...")
                    subdomain = f"{subdomain_base}-{counter}.{BASE_DOMAIN}"
                    counter += 1
                    
                    # Safety limit to prevent infinite loops
                    if counter > 100:
                        # Use UUID for guaranteed uniqueness
                        unique_id = uuid.uuid4().hex[:8]
                        subdomain = f"{subdomain_base}-{unique_id}.{BASE_DOMAIN}"
                        logger.warning(f"Hit counter limit, using UUID: {subdomain}")
                        break
                
                # NOW set the unique subdomain field
                django_project.subdomain = subdomain
                logger.info(f"Generated unique subdomain: {subdomain}")

                # Now it's safe to save the project
                try:
                    django_project.save()
                    logger.info(f"Django project saved with ID: {django_project.id}")
                    logger.info(f"Project file path: {django_project.project_file.path}")
                except Exception as save_error:
                    # This should not happen now, but handle it just in case
                    if "UNIQUE constraint failed" in str(save_error):
                        logger.error(f"Subdomain uniqueness error: {save_error}")
                        # Try one more time with UUID
                        unique_id = uuid.uuid4().hex[:8]
                        django_project.subdomain = f"{subdomain_base}-{unique_id}.{BASE_DOMAIN}"
                        django_project.save()
                        logger.info(f"Saved with UUID subdomain: {django_project.subdomain}")
                    else:
                        raise

                # Set project folder path with validation
                WEBSITES_ROOT = getattr(settings, 'WEBSITES_ROOT', 
                                      os.path.join(settings.MEDIA_ROOT, "websites"))
                
                os.makedirs(WEBSITES_ROOT, exist_ok=True)
                
                project_folder = os.path.join(WEBSITES_ROOT, f"{request.user.username}_{safe_name}")
                django_project.project_folder = project_folder
                django_project.deployment_status = 'deploying'
                django_project.save()

                # Deploy the project
                try:
                    deployment_result = deploy_django_project(
                        request.user.username,
                        safe_name,
                        django_project.project_file.path,
                        django_project.custom_domain
                    )
                    
                    logger.info(f"Deployment result: {deployment_result}")
                    
                    if deployment_result and isinstance(deployment_result, dict):
                        if deployment_result.get('success'):
                            # Successful deployment - use subdomain format
                            domain_name = deployment_result.get('domain_name')
                            port = deployment_result.get('port')
                            full_url = deployment_result.get('full_url', f"http://{domain_name}")
                            
                            django_project.domain_name = domain_name
                            django_project.is_active = True
                            django_project.deployment_status = 'deployed'
                            django_project.save()

                            logger.info(f"Django project deployed successfully: {domain_name}")
                            
                            # Display user-friendly message with subdomain
                            messages.success(
                                request, 
                                f"Django project deployed successfully! Visit: {full_url}"
                            )
                            return redirect('django_projects')
                        else:
                            # Deployment failed
                            error_msg = deployment_result.get('error', 'Unknown deployment error')
                            logger.error(f"Django deployment failed: {error_msg}")
                            django_project.deployment_status = 'failed'
                            django_project.save()
                            
                            # User-friendly error messages
                            if "Not a valid Django project" in error_msg:
                                messages.error(request, "Invalid Django project: Make sure your ZIP file contains manage.py and settings.py files.")
                            elif "Required file not found" in error_msg:
                                messages.error(request, "Missing required files in your Django project. Please check your project structure.")
                            elif "Permission denied" in error_msg:
                                messages.error(request, "Server permission error. Your project may still be deployed but some features might not work.")
                            elif "Invalid or corrupted ZIP file" in error_msg:
                                messages.error(request, "The uploaded file is invalid or corrupted. Please check your ZIP file and try again.")
                            else:
                                messages.error(request, f"Deployment failed: {error_msg}")
                    else:
                        # Legacy format fallback
                        if deployment_result and isinstance(deployment_result, str):
                            django_project.domain_name = deployment_result
                            django_project.is_active = True
                            django_project.deployment_status = 'deployed'
                            django_project.save()
                            messages.success(request, f"Django project deployed successfully! Visit: http://{deployment_result}")
                            return redirect('django_projects')
                        else:
                            django_project.deployment_status = 'failed'
                            django_project.save()
                            messages.error(request, "Django project deployment failed. Please check your project structure and requirements.")
                
                except Exception as deploy_error:
                    logger.error(f"Django deployment exception: {str(deploy_error)}")
                    django_project.deployment_status = 'failed'
                    django_project.save()
                    
                    error_msg = str(deploy_error)
                    
                    if "No such file or directory" in error_msg:
                        messages.error(request, f"File system error: {error_msg}")
                    elif "Permission denied" in error_msg:
                        messages.warning(request, "Permission warnings occurred during deployment. Your project may still work with limited functionality.")
                    elif "docker" in error_msg.lower():
                        messages.error(request, "Docker deployment error. Please check your project requirements and try again.")
                    elif "zipfile" in error_msg.lower() or "bad zip" in error_msg.lower():
                        messages.error(request, "Invalid ZIP file format. Please ensure your file is a valid ZIP archive.")
                    else:
                        messages.error(request, f"Deployment error: {error_msg}")

            except Exception as e:
                logger.error(f"Django deployment preparation error for user {request.user.username}: {str(e)}")
                
                # Handle UNIQUE constraint error specifically
                if "UNIQUE constraint failed" in str(e) and "subdomain" in str(e):
                    messages.error(request, "A project with this subdomain already exists. Please try a different project name or try again.")
                else:
                    messages.error(request, f"Deployment preparation failed: {str(e)}")
        else:
            # Form validation errors
            logger.error(f"Form validation errors: {form.errors}")
            
            for field, errors in form.errors.items():
                for error in errors:
                    if field == 'project_name':
                        messages.error(request, f"Project name error: {error}")
                    elif field == 'project_file':
                        messages.error(request, f"Project file error: {error}")
                    else:
                        messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
    else:
        form = DjangoProjectForm()

    return render(request, 'deploy_django.html', {'form': form})


@login_required
def toggle_django_project_status(request, project_id):
    """Toggle Django project active/inactive status"""
    try:
        project = get_object_or_404(DjangoProject, id=project_id, user=request.user)
        
        if request.method == 'POST':
            import json
            import subprocess
            data = json.loads(request.body)
            new_status = data.get('active', False)
            
            project.is_active = new_status
            
            if new_status:
                # Activate project
                safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
                project_folder = project.project_folder
                
                if project_folder and os.path.exists(project_folder):
                    # For simple deployment, just restart the server
                    message = 'Project is already running'
                    project.deployment_status = 'deployed'
                else:
                    project.deployment_status = 'failed'
                    project.is_active = False
                    message = 'Project folder not found'
            else:
                # Deactivate project
                project.deployment_status = 'stopped'
                message = 'Project deactivated successfully!'
            
            project.save()
            
            return JsonResponse({
                'success': True,
                'message': message,
                'status': project.deployment_status,
                'is_active': project.is_active
            })
        else:
            return JsonResponse({'success': False, 'error': 'Method not allowed'})
            
    except Exception as e:
        logger.error(f"Toggle status error for project {project_id}: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def django_projects_view(request):
    """List all Django projects with subdomain URLs"""
    projects = DjangoProject.objects.filter(user=request.user)
    
    # Update status for each project
    for project in projects:
        if project.domain_name and project.deployment_status != 'failed':
            safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
            try:
                status = check_django_deployment_status(
                    request.user.username,
                    safe_name,
                    project.domain_name
                )
                project.current_status = status
                
                # Update database status if needed
                if status.get('status') and not project.is_active:
                    project.is_active = True
                    project.deployment_status = 'deployed'
                    project.save()
                elif not status.get('status') and project.is_active:
                    project.is_active = False
                    project.deployment_status = 'error'
                    project.save()
                    
            except Exception as e:
                logger.error(f"Error checking status for project {project.id}: {e}")
                project.current_status = {'status': False, 'error': str(e)}
        else:
            project.current_status = {'status': False}
    
    return render(request, 'django_projects.html', {'projects': projects})


@login_required
def django_project_detail(request, project_id):
    """View Django project details with custom domain support"""
    project = get_object_or_404(DjangoProject, id=project_id, user=request.user)
    
    # Get detailed status
    status = {'status': False}
    if project.domain_name and project.deployment_status != 'failed':
        safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
        try:
            status = check_django_deployment_status(
                request.user.username,
                safe_name,
                project.domain_name
            )
        except Exception as e:
            logger.error(f"Error checking detailed status for project {project_id}: {e}")
            status = {'status': False, 'error': str(e)}
    
    # Get project info
    project_info = {}
    if project.project_folder and os.path.exists(project.project_folder):
        try:
            project_info = get_django_project_info(project.project_folder)
        except Exception as e:
            logger.error(f"Error getting project info for {project_id}: {e}")
            project_info = {'error': str(e)}
    
    # Determine access URL and type
    from .utils import get_local_ip
    server_ip = get_local_ip()
    
    has_custom_domain = bool(project.custom_domain)
    
    if has_custom_domain:
        # Custom domain configuration
        primary_url = f"http://{project.custom_domain}"
        fallback_url = f"http://{project.domain_name}" if project.domain_name != project.custom_domain else None
        dns_instructions = f"Create an A record: {project.custom_domain} → {server_ip}"
    else:
        # IP:Port configuration
        primary_url = f"http://{project.domain_name}" if project.domain_name else None
        fallback_url = None
        dns_instructions = None
    
    context = {
        'project': project,
        'status': status,
        'project_info': project_info,
        'has_custom_domain': has_custom_domain,
        'primary_url': primary_url,
        'fallback_url': fallback_url,
        'dns_instructions': dns_instructions,
        'server_ip': server_ip,
    }
    
    return render(request, 'django_project_detail.html', context)

@login_required
def delete_django_project(request, project_id):
    """Delete Django project and cleanup resources"""
    try:
        project = get_object_or_404(DjangoProject, id=project_id, user=request.user)
        safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
        
        # Cleanup deployment resources
        cleanup_django_deployment(request.user.username, safe_name)
        
        # Remove project files
        if project.project_folder and os.path.exists(project.project_folder):
            import shutil
            shutil.rmtree(project.project_folder, ignore_errors=True)
        
        # Delete database record
        project.delete()
        
        messages.success(request, "Django project deleted successfully!")
        
    except Exception as e:
        logger.error(f"Django project deletion error: {str(e)}")
        messages.error(request, f"Failed to delete project: {str(e)}")
    
    return redirect('django_projects')

@login_required
def restart_django_project(request, project_id):
    """Restart Django project"""
    import subprocess
    try:
        project = get_object_or_404(DjangoProject, id=project_id, user=request.user)
        safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
        
        project.deployment_status = 'restarting'
        project.save()
        
        project_folder = project.project_folder
        
        if project_folder and os.path.exists(project_folder):
            # Stop and restart the server
            from .utils import stop_django_project
            stop_django_project(request.user.username, safe_name)
            
            # Redeploy
            deployment_result = deploy_django_project(
                request.user.username,
                safe_name,
                project.project_file.path,
                project.custom_domain
            )
            
            if deployment_result and deployment_result.get('success'):
                project.deployment_status = 'deployed'
                project.save()
                messages.success(request, "Django project restarted successfully!")
            else:
                project.deployment_status = 'error'
                project.save()
                messages.error(request, "Failed to restart project")
        else:
            project.deployment_status = 'failed'
            project.save()
            messages.error(request, "Project folder not found!")
            
    except Exception as e:
        logger.error(f"Django project restart error: {str(e)}")
        messages.error(request, f"Failed to restart project: {str(e)}")
    
    return redirect('django_project_detail', project_id=project_id)

@login_required
def django_project_logs(request, project_id):
    """Get Django project logs"""
    import subprocess
    try:
        project = get_object_or_404(DjangoProject, id=project_id, user=request.user)
        safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
        
        # Get log file
        log_file = os.path.join(project.project_folder, f'{request.user.username}_{safe_name}.log')
        
        logs = ""
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    log_content = f.read()
                    # Get last 2000 characters
                    logs = log_content[-2000:] if len(log_content) > 2000 else log_content
            except Exception as e:
                logs = f"Error reading logs: {str(e)}"
        else:
            logs = "No logs available"
        
        return JsonResponse({'logs': logs, 'success': True})
        
    except Exception as e:
        return JsonResponse({'error': str(e), 'success': False})
    
@login_required
def update_django_project(request, project_id):
    """Update Django project with new code"""
    try:
        project = get_object_or_404(DjangoProject, id=project_id, user=request.user)
        
        if request.method == 'POST':
            project_file = request.FILES.get('project_file')
            
            if not project_file:
                return JsonResponse({'success': False, 'error': 'No file provided'})
            
            if not project_file.name.lower().endswith('.zip'):
                return JsonResponse({'success': False, 'error': 'Only ZIP files are allowed'})
            
            if project_file.size > 100 * 1024 * 1024:
                return JsonResponse({'success': False, 'error': 'File size exceeds 100MB limit'})
            
            try:
                # Stop current server
                from .utils import stop_django_project
                safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
                stop_django_project(request.user.username, safe_name)
                
                # Save new file
                project.project_file = project_file
                project.save()
                
                # Redeploy
                deployment_result = deploy_django_project(
                    request.user.username,
                    safe_name,
                    project.project_file.path,
                    project.custom_domain
                )
                
                if deployment_result and isinstance(deployment_result, dict) and deployment_result.get('success'):
                    project.deployment_status = 'deployed'
                    project.is_active = True
                    project.domain_name = deployment_result.get('domain_name')
                    project.save()
                    
                    return JsonResponse({
                        'success': True,
                        'message': 'Project updated successfully!',
                        'domain': deployment_result.get('domain_name')
                    })
                else:
                    project.deployment_status = 'failed'
                    project.is_active = False
                    project.save()
                    
                    error_msg = deployment_result.get('error', 'Deployment failed') if isinstance(deployment_result, dict) else 'Deployment failed'
                    return JsonResponse({'success': False, 'error': f'Update failed: {error_msg}'})
                    
            except Exception as e:
                logger.error(f"Project update error: {str(e)}")
                return JsonResponse({'success': False, 'error': f'Update error: {str(e)}'})
        else:
            return JsonResponse({'success': False, 'error': 'Method not allowed'})
            
    except Exception as e:
        logger.error(f"Update project error for project {project_id}: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def django_project_metrics(request, project_id):
    """Get Django project metrics"""
    import subprocess
    try:
        project = get_object_or_404(DjangoProject, id=project_id, user=request.user)
        safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
        
        metrics = {
            'cpu_usage': 0,
            'memory_usage': 0,
            'disk_usage': 0,
            'status': 'unknown'
        }
        
        try:
            # Check if process is running
            pid_file = os.path.join(project.project_folder, f'{request.user.username}_{safe_name}.pid')
            
            if os.path.exists(pid_file):
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                # Check if process exists
                import platform
                if platform.system() == 'Windows':
                    result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], 
                                          capture_output=True, text=True)
                    metrics['status'] = 'running' if str(pid) in result.stdout else 'stopped'
                else:
                    try:
                        os.kill(pid, 0)
                        metrics['status'] = 'running'
                    except:
                        metrics['status'] = 'stopped'
            else:
                metrics['status'] = 'stopped'
                
            # Get disk usage
            if project.project_folder and os.path.exists(project.project_folder):
                def get_dir_size(path):
                    total_size = 0
                    for dirpath, dirnames, filenames in os.walk(path):
                        for filename in filenames:
                            filepath = os.path.join(dirpath, filename)
                            try:
                                total_size += os.path.getsize(filepath)
                            except:
                                pass
                    return total_size
                
                size_bytes = get_dir_size(project.project_folder)
                size_mb = round(size_bytes / (1024 * 1024), 2)
                metrics['disk_usage'] = f"{size_mb} MB"
            
        except Exception as e:
            logger.error(f"Error getting metrics for project {project_id}: {e}")
            metrics['status'] = 'error'
        
        return JsonResponse({'success': True, 'metrics': metrics})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# Static Website Management
@login_required
def deploy_static_view(request):
    """Deploy static website"""
    domain_link = None
    
    if request.method == 'POST':
        form = WebsiteForm(request.POST, request.FILES)
        if form.is_valid():
            website = form.save(commit=False)
            website.user = request.user

            safe_title = "".join(c if c.isalnum() else "_" for c in website.title)
            unique_id = uuid.uuid4().hex[:6]
            website.subdomain = f"{request.user.username}-{safe_title}-{unique_id}".lower()

            WEBSITES_ROOT = getattr(settings, 'WEBSITES_ROOT', 
                                  os.path.join(settings.BASE_DIR, "media", "websites"))
            website.folder_name = os.path.join(WEBSITES_ROOT, f"{request.user.username}_{safe_title}")
            
            website.save()

            from .utils import deploy_website
            domain_link = deploy_website(
                request.user.username,
                safe_title,
                website.uploaded_file.path,
                is_dynamic=False,
                custom_domain=website.custom_domain
            )

            if domain_link:
                website.domain_name = domain_link
                website.is_active = True
                website.save()
                messages.success(request, f"Static website deployed! Visit: http://{domain_link}")
            else:
                messages.error(request, "Static website deployment failed.")
    else:
        form = WebsiteForm()

    return render(request, 'deploy_static.html', {'form': form, 'domain_link': domain_link})

@login_required
def websites(request):
    """List all static websites"""
    user_websites = Website.objects.filter(user=request.user)
    
    for website in user_websites:
        if website.domain_name:
            from .utils import check_deployment_status
            website.status = check_deployment_status(
                request.user.username, 
                website.title, 
                website.domain_name
            )
        else:
            website.status = False
    
    return render(request, 'websites.html', {'websites': user_websites})

@login_required
def delete_website(request, website_id):
    """Delete static website"""
    try:
        website = Website.objects.get(id=website_id, user=request.user)
        
        from .utils import cleanup_deployment
        safe_title = "".join(c if c.isalnum() else "_" for c in website.title)
        cleanup_deployment(request.user.username, safe_title)
        
        if website.folder_name and os.path.exists(website.folder_name):
            import shutil
            shutil.rmtree(website.folder_name)
        
        website.delete()
        messages.success(request, "Website deleted successfully!")
        
    except Website.DoesNotExist:
        messages.error(request, "Website not found!")
    except Exception as e:
        logger.error(f"Website deletion error: {str(e)}")
        messages.error(request, "Failed to delete website!")
    
    return redirect('websites')

@login_required
def settings_view(request):
    context = {
        'total_deployments': Website.objects.filter(user=request.user).count() + DjangoProject.objects.filter(user=request.user).count(),
        'active_sites': Website.objects.filter(user=request.user, is_active=True).count() + DjangoProject.objects.filter(user=request.user, is_active=True).count(),
        'storage_used': 0,
        'bandwidth_used': 0,
    }
    
    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        
        if form_type == 'profile':
            user = request.user
            user.email = request.POST.get('email')
            user.first_name = request.POST.get('first_name')
            user.last_name = request.POST.get('last_name')
            user.save()
            messages.success(request, 'Profile updated successfully!')
            
        elif form_type == 'password':
            pass
            
        elif form_type == 'deployment':
            pass
    
    return render(request, 'settings.html', context)



from django.db.models import Count, Q
from django.utils import timezone
import json
from datetime import datetime, timedelta
@login_required
def reports(request):
    """Comprehensive reports and analytics view"""
    user = request.user
    
    # Get all user's projects
    websites = Website.objects.filter(user=user)
    django_projects = DjangoProject.objects.filter(user=user)
    
    # Basic stats
    total_static_sites = websites.count()
    total_django_projects = django_projects.count()
    total_deployments = total_static_sites + total_django_projects
    
    active_static_sites = websites.filter(is_active=True).count()
    active_django_projects = django_projects.filter(is_active=True).count()
    active_sites = active_static_sites + active_django_projects
    
    # Calculate success rate (percentage of active vs total)
    success_rate = round((active_sites / total_deployments * 100) if total_deployments > 0 else 0, 1)
    
    # Calculate storage usage (in MB)
    storage_used = 0
    for website in websites:
        try:
            if website.uploaded_file and hasattr(website.uploaded_file, 'size'):
                storage_used += website.uploaded_file.size
        except:
            pass
    
    for project in django_projects:
        try:
            if project.project_file and hasattr(project.project_file, 'size'):
                storage_used += project.project_file.size
        except:
            pass
    
    storage_used = round(storage_used / (1024 * 1024), 2)  # Convert to MB
    
    # Generate deployment timeline data (last 30 days)
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=30)
    
    deployment_dates = []
    deployment_counts = []
    
    # Create date range for the last 30 days
    current_date = start_date
    while current_date <= end_date:
        deployment_dates.append(current_date.strftime('%m/%d'))
        
        # Count deployments for this date
        daily_websites = websites.filter(created_at__date=current_date).count()
        daily_django = django_projects.filter(created_at__date=current_date).count()
        daily_total = daily_websites + daily_django
        
        deployment_counts.append(daily_total)
        current_date += timedelta(days=1)
    
    # Recent deployments (last 10)
    recent_websites = list(websites.order_by('-created_at')[:5])
    recent_django = list(django_projects.order_by('-created_at')[:5])
    
    # Combine and sort recent deployments
    recent_deployments = recent_websites + recent_django
    recent_deployments.sort(key=lambda x: x.created_at, reverse=True)
    recent_deployments = recent_deployments[:10]
    
    # All projects for the table (combine both types)
    all_projects = []
    
    # Add websites
    for website in websites.order_by('-created_at'):
        all_projects.append({
            'title': website.title,
            'project_name': None,  # This helps distinguish in template
            'is_active': website.is_active,
            'domain_name': website.domain_name,
            'created_at': website.created_at,
            'project_file': None,
            'uploaded_file': website.uploaded_file
        })
    
    # Add Django projects
    for project in django_projects.order_by('-created_at'):
        all_projects.append({
            'title': None,
            'project_name': project.project_name,
            'is_active': project.is_active,
            'domain_name': project.domain_name,
            'created_at': project.created_at,
            'project_file': project.project_file,
            'uploaded_file': None
        })
    
    # Sort all projects by creation date
    all_projects.sort(key=lambda x: x['created_at'], reverse=True)
    
    # Convert objects to template-friendly format
    all_projects_formatted = []
    for project in all_projects:
        project_data = type('obj', (object,), project)
        all_projects_formatted.append(project_data)
    
    context = {
        # Basic stats
        'total_deployments': total_deployments,
        'total_static_sites': total_static_sites,
        'total_django_projects': total_django_projects,
        'active_sites': active_sites,
        'active_static_sites': active_static_sites,
        'active_django_projects': active_django_projects,
        'storage_used': storage_used,
        'success_rate': success_rate,
        
        # Chart data
        'deployment_dates': json.dumps(deployment_dates),
        'deployment_counts': json.dumps(deployment_counts),
        'django_count': total_django_projects,
        'static_count': total_static_sites,
        
        # Lists
        'recent_deployments': recent_deployments,
        'all_projects': all_projects_formatted,
        
        # Additional stats
        'websites': websites,
        'django_projects': django_projects,
    }
    
    return render(request, 'reports.html', context)

@login_required
def update_custom_domain(request, project_id):
    """Add or update custom domain for a Django project"""
    if request.method == 'POST':
        try:
            project = get_object_or_404(DjangoProject, id=project_id, user=request.user)
            custom_domain = request.POST.get('custom_domain', '').strip()
            
            if not custom_domain:
                return JsonResponse({'success': False, 'error': 'Domain name is required'})
            
            # Validate domain format (basic validation)
            import re
            domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
            if not re.match(domain_pattern, custom_domain):
                return JsonResponse({'success': False, 'error': 'Invalid domain format'})
            
            # Remove http:// or https:// if user included it
            custom_domain = custom_domain.replace('http://', '').replace('https://', '').rstrip('/')
            
            # Update project with custom domain
            project.custom_domain = custom_domain
            project.save()
            
            # Get server IP for DNS instructions
            from .utils import get_local_ip
            server_ip = get_local_ip()
            
            # Restart project to apply changes (optional)
            try:
                safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
                from .utils import stop_django_project, deploy_django_project
                
                # Stop existing server
                stop_django_project(request.user.username, safe_name)
                
                # Redeploy with custom domain
                deployment_result = deploy_django_project(
                    request.user.username,
                    safe_name,
                    project.project_file.path,
                    custom_domain
                )
                
                if deployment_result and deployment_result.get('success'):
                    project.domain_name = custom_domain
                    project.deployment_status = 'deployed'
                    project.is_active = True
                    project.save()
                    
                    access_url = f"http://{custom_domain}"
                    dns_instructions = f"Create an A record: {custom_domain} → {server_ip}"
                    
                    return JsonResponse({
                        'success': True,
                        'message': 'Custom domain configured successfully!',
                        'access_url': access_url,
                        'dns_instructions': dns_instructions,
                        'server_ip': server_ip
                    })
                else:
                    error_msg = deployment_result.get('error', 'Deployment failed') if isinstance(deployment_result, dict) else 'Deployment failed'
                    return JsonResponse({
                        'success': False,
                        'error': f'Failed to redeploy with custom domain: {error_msg}'
                    })
                    
            except Exception as e:
                logger.error(f"Error redeploying with custom domain: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'error': f'Configuration error: {str(e)}'
                })
                
        except Exception as e:
            logger.error(f"Error updating custom domain: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def remove_custom_domain(request, project_id):
    """Remove custom domain and revert to IP:port access"""
    if request.method == 'POST':
        try:
            project = get_object_or_404(DjangoProject, id=project_id, user=request.user)
            
            # Clear custom domain
            project.custom_domain = None
            
            # Get current IP and port
            from .utils import get_local_ip
            server_ip = get_local_ip()
            
            # Get port from project folder
            safe_name = "".join(c if c.isalnum() else "_" for c in project.project_name)
            project_folder = os.path.join(settings.MEDIA_ROOT, "websites", f"{request.user.username}_{safe_name}")
            port_file = os.path.join(project_folder, f'{request.user.username}_{safe_name}.port')
            
            port = 8000
            if os.path.exists(port_file):
                try:
                    with open(port_file, 'r') as f:
                        port = int(f.read().strip())
                except:
                    pass
            
            # Update domain name to IP:port format
            new_domain = f"{server_ip}:{port}"
            project.domain_name = new_domain
            project.save()
            
            # Restart project with new configuration (optional)
            try:
                from .utils import stop_django_project, deploy_django_project
                
                # Stop existing server
                stop_django_project(request.user.username, safe_name)
                
                # Redeploy without custom domain
                deployment_result = deploy_django_project(
                    request.user.username,
                    safe_name,
                    project.project_file.path,
                    None  # No custom domain
                )
                
                if deployment_result and deployment_result.get('success'):
                    new_domain = deployment_result.get('domain_name')
                    project.domain_name = new_domain
                    project.deployment_status = 'deployed'
                    project.is_active = True
                    project.save()
                    
                    return JsonResponse({
                        'success': True,
                        'message': 'Custom domain removed successfully!',
                        'new_access_url': f"http://{new_domain}"
                    })
                else:
                    return JsonResponse({
                        'success': False,
                        'error': 'Failed to redeploy project'
                    })
                    
            except Exception as e:
                logger.error(f"Error redeploying after domain removal: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'error': f'Redeployment error: {str(e)}'
                })
                
        except Exception as e:
            logger.error(f"Error removing custom domain: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})







######################################STORAGE DATA#######################################################################
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import UserFile, StorageSettings, PaymentRequest
from .forms import FileUploadForm, PaymentRequestForm

@login_required
def reports(request):
    """Comprehensive reports and analytics view"""
    import os
    from django.core.files.storage import default_storage
    
    user = request.user
    
    # Get all user's projects
    websites = Website.objects.filter(user=user)
    django_projects = DjangoProject.objects.filter(user=user)
    
    # Basic stats
    total_static_sites = websites.count()
    total_django_projects = django_projects.count()
    total_deployments = total_static_sites + total_django_projects
    
    active_static_sites = websites.filter(is_active=True).count()
    active_django_projects = django_projects.filter(is_active=True).count()
    active_sites = active_static_sites + active_django_projects
    
    # Calculate success rate (percentage of active vs total)
    success_rate = round((active_sites / total_deployments * 100) if total_deployments > 0 else 0, 1)
    
    # Calculate storage usage (in MB)
    storage_used = 0
    
    # Process websites
    for website in websites:
        try:
            if website.uploaded_file:
                # Check if file actually exists before accessing size
                if default_storage.exists(website.uploaded_file.name):
                    storage_used += website.uploaded_file.size
                else:
                    # Optional: Log missing files
                    print(f"Warning: File not found for website {website.id}: {website.uploaded_file.name}")
        except Exception as e:
            print(f"Error processing website {website.id}: {e}")
            pass
    
    # Process Django projects
    for project in django_projects:
        try:
            if project.project_file:
                # Check if file actually exists before accessing size
                if default_storage.exists(project.project_file.name):
                    storage_used += project.project_file.size
                else:
                    # Optional: Log missing files
                    print(f"Warning: File not found for project {project.id}: {project.project_file.name}")
        except Exception as e:
            print(f"Error processing project {project.id}: {e}")
            pass
    
    storage_used = round(storage_used / (1024 * 1024), 2)  # Convert to MB
    
    # Generate deployment timeline data (last 30 days)
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=30)
    
    deployment_dates = []
    deployment_counts = []
    
    # Create date range for the last 30 days
    current_date = start_date
    while current_date <= end_date:
        deployment_dates.append(current_date.strftime('%m/%d'))
        
        # Count deployments for this date
        daily_websites = websites.filter(created_at__date=current_date).count()
        daily_django = django_projects.filter(created_at__date=current_date).count()
        daily_total = daily_websites + daily_django
        
        deployment_counts.append(daily_total)
        current_date += timedelta(days=1)
    
    # Recent deployments (last 10)
    recent_websites = list(websites.order_by('-created_at')[:5])
    recent_django = list(django_projects.order_by('-created_at')[:5])
    
    # Combine and sort recent deployments
    recent_deployments = recent_websites + recent_django
    recent_deployments.sort(key=lambda x: x.created_at, reverse=True)
    recent_deployments = recent_deployments[:10]
    
    # All projects for the table (combine both types)
    all_projects = []
    
    # Add websites
    for website in websites.order_by('-created_at'):
        # Check if file exists for size display
        file_size = None
        if website.uploaded_file:
            try:
                if default_storage.exists(website.uploaded_file.name):
                    file_size = website.uploaded_file.size
            except:
                pass
        
        all_projects.append({
            'title': website.title,
            'project_name': None,
            'is_active': website.is_active,
            'domain_name': website.domain_name,
            'created_at': website.created_at,
            'project_file': None,
            'uploaded_file': website.uploaded_file if file_size else None,
            'file_size': file_size,
        })
    
    # Add Django projects
    for project in django_projects.order_by('-created_at'):
        # Check if file exists for size display
        file_size = None
        if project.project_file:
            try:
                if default_storage.exists(project.project_file.name):
                    file_size = project.project_file.size
            except:
                pass
        
        all_projects.append({
            'title': None,
            'project_name': project.project_name,
            'is_active': project.is_active,
            'domain_name': project.domain_name,
            'created_at': project.created_at,
            'project_file': project.project_file if file_size else None,
            'uploaded_file': None,
            'file_size': file_size,
        })
    
    # Sort all projects by creation date
    all_projects.sort(key=lambda x: x['created_at'], reverse=True)
    
    # Convert objects to template-friendly format
    all_projects_formatted = []
    for project in all_projects:
        project_data = type('obj', (object,), project)
        all_projects_formatted.append(project_data)
    
    context = {
        # Basic stats
        'total_deployments': total_deployments,
        'total_static_sites': total_static_sites,
        'total_django_projects': total_django_projects,
        'active_sites': active_sites,
        'active_static_sites': active_static_sites,
        'active_django_projects': active_django_projects,
        'storage_used': storage_used,
        'success_rate': success_rate,
        
        # Chart data
        'deployment_dates': json.dumps(deployment_dates),
        'deployment_counts': json.dumps(deployment_counts),
        'django_count': total_django_projects,
        'static_count': total_static_sites,
        
        # Lists
        'recent_deployments': recent_deployments,
        'all_projects': all_projects_formatted,
        
        # Additional stats
        'websites': websites,
        'django_projects': django_projects,
    }
    
    return render(request, 'reports.html', context)

@login_required
def upload_file(request):
    # Get storage settings
    settings, _ = StorageSettings.objects.get_or_create(
        id=1,
        defaults={'price_per_gb': 5.00, 'free_limit_gb': 1.0}
    )

    # Total GB user purchased (approved payments)
    approved_payments = PaymentRequest.objects.filter(user=request.user, status='approved')
    purchased_gb = sum([p.gb_requested for p in approved_payments])

    # Total allowed storage in bytes
    total_allowed_gb = settings.free_limit_gb + purchased_gb
    total_allowed_bytes = total_allowed_gb * 1024 * 1024 * 1024

    # Total already used storage in bytes
    total_used_bytes = sum(f.file.size for f in UserFile.objects.filter(user=request.user))

    if request.method == 'POST':
        form = FileUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['file']

            if total_used_bytes + uploaded_file.size > total_allowed_bytes:
                messages.error(request, "❌ Storage limit exceeded! Please buy more storage.")
                return redirect('payment_page')

            file_obj = form.save(commit=False)
            file_obj.user = request.user
            file_obj.save()
            messages.success(request, "✅ File uploaded successfully!")
            return redirect('upload_list')
    else:
        form = FileUploadForm()

    return render(request, 'storage/upload.html', {
        'form': form,
        'used_gb': total_used_bytes / (1024 ** 3),
        'free_limit_gb': total_allowed_gb,  # show total allowed GB including purchased
    })

@login_required
def upload_list(request):
    user_files = UserFile.objects.filter(user=request.user).order_by('-uploaded_at')

    # Storage stats
    storage_settings, _ = StorageSettings.objects.get_or_create(
        id=1,
        defaults={'price_per_gb': 5.00, 'free_limit_gb': 1.0}
    )
    approved_payments = PaymentRequest.objects.filter(user=request.user, status='approved')
    purchased_gb = sum(float(p.gb_requested) for p in approved_payments)
    total_gb = float(storage_settings.free_limit_gb) + purchased_gb

    used_bytes = 0
    files = []

    for f in user_files:
        file_path = os.path.join(settings.MEDIA_ROOT, str(f.file))
        if os.path.exists(file_path):
            size_bytes = os.path.getsize(file_path)
            used_bytes += size_bytes

            # Determine file type
            ext = f.file.name.split('.')[-1].lower()
            if ext in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']:
                file_type = 'image'
            elif ext in ['mp4', 'mov', 'avi', 'mkv', 'webm']:
                file_type = 'video'
            elif ext in ['mp3', 'wav', 'ogg', 'm4a']:
                file_type = 'audio'
            else:
                file_type = 'other'

            files.append({
                'id': f.id,
                'title': f.title,
                'url': f.file.url,
                'uploaded_at': f.uploaded_at,
                'size_mb': round(size_bytes / (1024*1024), 2),
                'type': file_type
            })
        else:
            # File missing – optional: log or delete DB record
            print(f"⚠️ Missing file: {file_path}")
            # f.delete()  # uncomment if you want to remove missing files from DB

    used_gb = used_bytes / (1024 ** 3)
    remaining_gb = max(total_gb - used_gb, 0)  # prevents negative

    return render(request, 'storage/upload_list.html', {
        'files': files,
        'total_gb': round(total_gb, 2),
        'used_gb': round(used_gb, 2),
        'remaining_gb': round(remaining_gb, 2),
    })

@login_required
def payment_page(request):
    # Get or create storage settings
    settings, _ = StorageSettings.objects.get_or_create(
        id=1,
        defaults={'price_per_gb': 5.00, 'free_limit_gb': 1.0}
    )

    # Get the user's latest payment request
    latest_request = PaymentRequest.objects.filter(user=request.user).order_by('-requested_at').first()

    # Get all requests for history
    payment_history = PaymentRequest.objects.filter(user=request.user).order_by('-requested_at')

    # Handle new payment submission
    if request.method == 'POST':
        form = PaymentRequestForm(request.POST, request.FILES)
        if form.is_valid():
            payment_request = form.save(commit=False)
            payment_request.user = request.user
            payment_request.amount = float(payment_request.gb_requested) * float(settings.price_per_gb)
            payment_request.qr_image = 'storage/qr_code.jpg'  # Static admin QR
            payment_request.save()
            messages.success(request, "✅ Payment submitted successfully!")
            return redirect('payment_page')
    else:
        form = PaymentRequestForm()

    return render(request, 'storage/payment.html', {
        'settings': settings,
        'latest_request': latest_request,
        'form': form,
        'payment_history': payment_history,  # Added
    })


from decimal import Decimal


@login_required
def storage_overview(request):
    # Get or create storage settings
    storage_settings, _ = StorageSettings.objects.get_or_create(
        id=1,
        defaults={'price_per_gb': 5.00, 'free_limit_gb': 1.0}
    )

    # Approved purchased storage
    approved_payments = PaymentRequest.objects.filter(user=request.user, status='approved')
    purchased_gb = sum(float(p.gb_requested) for p in approved_payments)

    # Total available storage (free + purchased)
    total_storage_gb = float(storage_settings.free_limit_gb) + purchased_gb

    # Calculate used storage safely
    user_files = UserFile.objects.filter(user=request.user)
    used_bytes = 0
    file_reports = []

    for f in user_files:
        file_path = os.path.join(settings.MEDIA_ROOT, str(f.file))
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            used_bytes += file_size
            file_reports.append({
                'name': os.path.basename(f.file.name),
                'size_mb': round(file_size / (1024 * 1024), 2),
                'uploaded_at': f.uploaded_at
            })
        else:
            # File missing — you can optionally clean it up
            print(f"⚠️ Missing file: {file_path}")
            # f.delete()  # Uncomment if you want to auto-delete DB entry

    used_gb = used_bytes / (1024 ** 3)
    remaining_gb = max(total_storage_gb - used_gb, 0)  # prevents negative

    return render(request, 'storage/storage_overview.html', {
        'total_storage_gb': round(total_storage_gb, 2),
        'used_gb': round(used_gb, 2),
        'remaining_gb': round(remaining_gb, 2),
        'file_reports': file_reports,
    })

def help_view(request):
    """
    Renders the Help & Support page with developer info,
    website details, and floating WhatsApp button.
    """
    return render(request, 'help.html')









################Github Deployment Metrics##########################################
import sys
import subprocess
import re
import psutil
import shutil
import os
import threading
from pathlib import Path

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.db import transaction

try:
    from git import Repo, GitCommandError
    from git.cmd import Git
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False

from .forms import DeployForm
from .models import DeployedProject

PYTHON = sys.executable
MAIN_DOMAIN = getattr(settings, 'MAIN_DOMAIN', 'samitchaudhary.com.np')


def clone_repository_background(repo_url, project_dir, project_id):
    """Clone repository in background thread"""
    try:
        if not project_dir.exists():
            project_dir.parent.mkdir(parents=True, exist_ok=True)
            Repo.clone_from(repo_url, str(project_dir), depth=1)
        else:
            repo = Repo(str(project_dir))
            repo.remotes.origin.pull()
        
        # Update project status
        project = DeployedProject.objects.get(id=project_id)
        project.clone_status = 'completed'
        project.save()
    except Exception as e:
        project = DeployedProject.objects.get(id=project_id)
        project.clone_status = f'failed: {str(e)[:200]}'
        project.save()


def check_git_installation():
    """Check if git is properly installed and accessible"""
    if not GIT_AVAILABLE:
        raise EnvironmentError(
            "GitPython is not installed. Install with: pip install gitpython"
        )
    
    git_path = shutil.which('git')
    
    if not git_path:
        common_paths = [
            '/usr/bin/git',
            '/usr/local/bin/git',
            '/bin/git',
            'C:\\Program Files\\Git\\bin\\git.exe',
            'C:\\Program Files (x86)\\Git\\bin\\git.exe',
        ]
        for path in common_paths:
            if os.path.exists(path):
                git_path = path
                break
    
    if not git_path:
        raise EnvironmentError(
            "Git is not found. Please install git:\n"
            "Windows: https://git-scm.com/download/win\n"
            "Linux: sudo apt install git -y"
        )
    
    try:
        Git.GIT_PYTHON_GIT_EXECUTABLE = git_path
    except Exception as e:
        raise EnvironmentError(f"Failed to configure git: {e}")
    
    return git_path


def validate_repo_url(url):
    """Validate GitHub repository URL"""
    pattern = r'^https://github\.com/[\w-]+/[\w.-]+(?:\.git)?$'
    return bool(re.match(pattern, url))


def validate_project_name(name):
    """Ensure project name is safe for filesystem and Python imports"""
    pattern = r'^[a-zA-Z][a-zA-Z0-9_-]{0,50}$'
    return bool(re.match(pattern, name))


def is_port_available(port):
    """Check if port is actually available on the system"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('0.0.0.0', port))
            return True
    except OSError:
        return False


def get_available_port(start_port=8000, end_port=9000):
    """Find an available port in the specified range"""
    for port in range(start_port, end_port):
        if is_port_available(port) and not DeployedProject.objects.filter(port=port).exists():
            return port
    return None


def setup_nginx_subdomain(project_name, port):
    """Create Nginx configuration for subdomain routing using sudo"""
    if sys.platform == 'win32':
        return False, "Nginx configuration skipped (Windows environment)"
    
    nginx_config = f"""server {{
    listen 80;
    server_name {project_name}.{MAIN_DOMAIN};

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location /static/ {{
        alias /var/www/{project_name}/static/;
        expires 30d;
    }}

    location /media/ {{
        alias /var/www/{project_name}/media/;
        expires 30d;
    }}
}}
"""
    
    try:
        # Write config to a temporary file first
        temp_config = Path(f"/tmp/nginx_{project_name}.conf")
        temp_config.write_text(nginx_config)
        
        nginx_conf_path = f"/etc/nginx/sites-available/{project_name}.{MAIN_DOMAIN}"
        nginx_enabled_path = f"/etc/nginx/sites-enabled/{project_name}.{MAIN_DOMAIN}"
        
        # Use sudo to move the config file
        result = subprocess.run(
            ['sudo', 'mv', str(temp_config), nginx_conf_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return False, f"Failed to create nginx config: {result.stderr}"
        
        # Create symbolic link with sudo
        subprocess.run(
            ['sudo', 'ln', '-sf', nginx_conf_path, nginx_enabled_path],
            capture_output=True,
            text=True,
            timeout=5,
            check=True
        )
        
        # Test Nginx configuration
        result = subprocess.run(
            ['sudo', 'nginx', '-t'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return False, f"Nginx config test failed: {result.stderr}"
        
        # Reload Nginx
        subprocess.run(
            ['sudo', 'systemctl', 'reload', 'nginx'],
            capture_output=True,
            text=True,
            timeout=10,
            check=True
        )
        
        return True, f"Nginx configured successfully for {project_name}.{MAIN_DOMAIN}"
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if hasattr(e.stderr, 'decode') else str(e)
        return False, f"Command failed: {error_msg[:200]}"
    except subprocess.TimeoutExpired:
        return False, "Nginx command timed out"
    except FileNotFoundError:
        return False, "sudo command not found. Install sudo or run as root."
    except Exception as e:
        return False, f"Failed to setup Nginx: {str(e)[:200]}"


def remove_nginx_subdomain(project_name):
    """Remove Nginx configuration for a subdomain"""
    if sys.platform == 'win32':
        return True, "Nginx not configured (Windows)"
    
    nginx_conf_path = Path(f"/etc/nginx/sites-available/{project_name}.{MAIN_DOMAIN}")
    nginx_enabled_path = Path(f"/etc/nginx/sites-enabled/{project_name}.{MAIN_DOMAIN}")
    
    try:
        if nginx_enabled_path.exists():
            nginx_enabled_path.unlink()
        if nginx_conf_path.exists():
            nginx_conf_path.unlink()
        
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True, timeout=10)
        return True, "Nginx configuration removed"
    except Exception as e:
        return False, f"Failed to remove Nginx config: {str(e)}"


def github_view(request):
    """Deploy a GitHub repository with subdomain support"""
    try:
        git_path = check_git_installation()
    except EnvironmentError as e:
        messages.error(request, str(e))
        form = DeployForm()
        projects = DeployedProject.objects.order_by('-created_at')[:10]
        return render(request, "github/hosting/deploy_form.html", {
            "form": form,
            "projects": projects,
            "main_domain": MAIN_DOMAIN
        })
    
    if request.method == "POST":
        form = DeployForm(request.POST)
        if form.is_valid():
            repo_url = form.cleaned_data["repo_url"].strip()

            if not validate_repo_url(repo_url):
                messages.error(request, "Invalid repository URL. Only GitHub HTTPS URLs are allowed.")
                return render(request, "github/hosting/deploy_form.html", {"form": form})

            project_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            
            if not validate_project_name(project_name):
                messages.error(request, f"Invalid project name: {project_name}. Must be alphanumeric.")
                return render(request, "github/hosting/deploy_form.html", {"form": form})

            if DeployedProject.objects.filter(name=project_name).exists():
                messages.error(request, f"Project '{project_name}' already exists.")
                return render(request, "github/hosting/deploy_form.html", {"form": form})

            project_dir = Path(settings.USER_PROJECTS_DIR) / project_name

            with transaction.atomic():
                port = get_available_port()
                if not port:
                    messages.error(request, "No available ports. Please contact administrator.")
                    return render(request, "github/hosting/deploy_form.html", {"form": form})

                # Create project record first
                dp = DeployedProject.objects.create(
                    name=project_name,
                    repo_url=repo_url,
                    port=port,
                    running=False,
                    clone_status='cloning'  # Add this field to your model
                )

                # Start cloning in background thread
                clone_thread = threading.Thread(
                    target=clone_repository_background,
                    args=(repo_url, project_dir, dp.id),
                    daemon=True
                )
                clone_thread.start()

                messages.success(
                    request,
                    f"Deployment started for {project_name}. Repository is being cloned in the background. "
                    f"Please wait a few moments and refresh the hosted projects page."
                )
                
                return redirect("hosted_projects")

    else:
        form = DeployForm()

    projects = DeployedProject.objects.order_by('-created_at')[:10]
    return render(request, "github/hosting/deploy_form.html", {
        "form": form,
        "projects": projects,
        "main_domain": MAIN_DOMAIN
    })


def github_success(request, pk):
    """Display deployment success page"""
    dp = get_object_or_404(DeployedProject, pk=pk)
    
    if dp.pid:
        try:
            proc = psutil.Process(dp.pid)
            dp.running = proc.is_running()
        except psutil.NoSuchProcess:
            dp.running = False
        except Exception:
            dp.running = False
        dp.save()
    
    return render(request, "github/hosting/deploy_success.html", {
        "project": dp,
        "main_domain": MAIN_DOMAIN
    })


def hosted_projects(request):
    """List all hosted projects with live status"""
    projects = DeployedProject.objects.order_by('-created_at')
    
    for project in projects:
        if project.pid:
            try:
                proc = psutil.Process(project.pid)
                project.running = proc.is_running()
            except psutil.NoSuchProcess:
                project.running = False
            except Exception:
                project.running = False
            project.save()
    
    return render(request, "github/hosting/hosted_projects.html", {
        "projects": projects,
        "main_domain": MAIN_DOMAIN
    })


def stop_project(request, pk):
    """Stop a running project and remove Nginx configuration"""
    if request.method == "POST":
        project = get_object_or_404(DeployedProject, pk=pk)
        
        if project.pid:
            try:
                proc = psutil.Process(project.pid)
                proc.terminate()
                proc.wait(timeout=10)
                project.running = False
                project.save()
                messages.success(request, f"Stopped {project.name}")
            except psutil.NoSuchProcess:
                project.running = False
                project.save()
                messages.warning(request, "Process was not running")
            except psutil.TimeoutExpired:
                try:
                    proc.kill()
                    project.running = False
                    project.save()
                    messages.warning(request, "Process forcefully killed")
                except Exception:
                    messages.error(request, "Failed to stop process")
            except Exception as e:
                messages.error(request, f"Error stopping process: {str(e)[:200]}")
        
        nginx_success, nginx_msg = remove_nginx_subdomain(project.name)
        if not nginx_success and sys.platform != 'win32':
            messages.warning(request, f"Nginx cleanup warning: {nginx_msg}")
        
        return redirect("hosted_projects")
    
    return redirect("hosted_projects")