from django.contrib import admin
from .models import UserVideo
from .models import ProfileImage

@admin.register(UserVideo)
class UserVideoAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'video', 'uploaded_at')
    search_fields = ('title',)
    list_filter = ('uploaded_at',)
    ordering = ('-uploaded_at',)


@admin.register(ProfileImage)
class ProfileImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'userId', 'image_tag', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('userId',)
    readonly_fields = ('uploaded_at', 'image_tag')

    # Show thumbnail in admin list/detail
    def image_tag(self, obj):
        if obj.image:
            return f'<img src="{obj.image.url}" width="100" height="100" />'
        return "-"
    image_tag.allow_tags = True
    image_tag.short_description = 'Image'