from django.urls import path
from . import views

urlpatterns = [
    # Public pages
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('plans/', views.plans, name='plans'),
    path('contact/', views.contact, name='contact'),

    # Authentication
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('dashboard/settings/', views.settings_view, name='settings'),
    path('dashboard/reports/', views.reports, name='reports'),

    # Django Project Management
    path('dashboard/django/', views.django_projects_view, name='django_projects'),
    path('dashboard/django/deploy/', views.deploy_django_view, name='deploy_django'),
    path('dashboard/django/<int:project_id>/', views.django_project_detail, name='django_project_detail'),
    path('dashboard/django/<int:project_id>/delete/', views.delete_django_project, name='delete_django_project'),
    path('dashboard/django/<int:project_id>/restart/', views.restart_django_project, name='restart_django_project'),
    path('dashboard/django/<int:project_id>/logs/', views.django_project_logs, name='django_project_logs'),

    # Github Integration
    path("github/", views.github_view, name="github_deploy"),
    path("success/<int:pk>/", views.github_success, name="github_success"),
    path("hosted-projects/", views.hosted_projects, name="hosted_projects"),
    
    
    # Custom Domain Management (NEW)
    path('django-project/<int:project_id>/update-domain/', views.update_custom_domain, name='update_custom_domain'),
    path('django-project/<int:project_id>/remove-domain/', views.remove_custom_domain, name='remove_custom_domain'),

    # New enhanced Django project features
    path('dashboard/django/<int:project_id>/toggle-status/', views.toggle_django_project_status, name='toggle_django_project_status'),
    path('dashboard/django/<int:project_id>/update/', views.update_django_project, name='update_django_project'),
    path('dashboard/django/<int:project_id>/metrics/', views.django_project_metrics, name='django_project_metrics'),


    # Static Website Management
    path('dashboard/websites/', views.websites, name='websites'),
    path('dashboard/websites/deploy/', views.deploy_static_view, name='deploy_static'),
    path('dashboard/websites/<int:website_id>/delete/', views.delete_website, name='delete_website'),


    # Storage Management
    path('upload/', views.upload_file, name='upload_file'),
    path('my-uploads/', views.upload_list, name='upload_list'),
    path('payment/', views.payment_page, name='payment_page'),
    path('storage-overview/', views.storage_overview, name='storage_overview'),


    path('help/', views. help_view, name='help'),
      
]

