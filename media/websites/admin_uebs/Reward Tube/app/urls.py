from django.urls import path
from .views import VideoUploadView
from .views import ProfileImageUploadView

urlpatterns = [
    path('videos/', VideoUploadView.as_view(), name='video-upload'),
      path('profile-images/', ProfileImageUploadView.as_view(), name='profile_image_upload'),
    
]
