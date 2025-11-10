from rest_framework import serializers
from .models import UserVideo
from .models import ProfileImage

class UserVideoSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserVideo
        fields = '__all__'


class ProfileImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProfileImage
        fields = ['id', 'userId', 'image', 'uploaded_at']