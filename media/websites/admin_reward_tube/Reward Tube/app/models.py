from django.db import models


class UserVideo(models.Model):
    title = models.CharField(max_length=100)
    video = models.FileField(upload_to='videos/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class ProfileImage(models.Model):
    userId = models.CharField(max_length=100)  # Store user ID as plain string
    image = models.ImageField(upload_to='profile_images/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.userId} - {self.id}"