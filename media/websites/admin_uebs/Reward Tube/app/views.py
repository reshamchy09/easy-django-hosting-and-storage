from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import UserVideo
from .serializers import UserVideoSerializer

from .models import ProfileImage
from .serializers import ProfileImageSerializer

class VideoUploadView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = UserVideoSerializer(data=request.data)
        if serializer.is_valid():
            video = serializer.save()  # Save the video instance

            # Build full URL
            video_url = request.build_absolute_uri(video.video.url)

            # Return all details including URL
            return Response({
                'id': video.id,
                'title': video.title,
                'url': video_url,
                'uploaded_at': video.uploaded_at
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        videos = UserVideo.objects.all().order_by('-uploaded_at')
        serializer = UserVideoSerializer(videos, many=True)

        # Add full URL for each video
        video_list = []
        for vid in videos:
            video_list.append({
                'id': vid.id,
                'title': vid.title,
                'url': request.build_absolute_uri(vid.video.url),
                'uploaded_at': vid.uploaded_at
            })

        return Response(video_list)







class ProfileImageUploadView(APIView):
    def post(self, request, *args, **kwargs):
        user_id = request.data.get("userId")
        if not user_id:
            return Response({"error": "userId is required"}, status=status.HTTP_400_BAD_REQUEST)

        image_file = request.FILES.get('image')
        if not image_file:
            return Response({"error": "No image uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        profile_image = ProfileImage.objects.create(userId=user_id, image=image_file)
        image_url = request.build_absolute_uri(profile_image.image.url)

        return Response({
            "id": profile_image.id,
            "userId": user_id,
            "url": image_url,
            "uploaded_at": profile_image.uploaded_at
        }, status=status.HTTP_201_CREATED)

    def get(self, request):
        images = ProfileImage.objects.all().order_by('-uploaded_at')
        response_data = []
        for img in images:
            response_data.append({
                "id": img.id,
                "userId": img.userId,
                "url": request.build_absolute_uri(img.image.url),
                "uploaded_at": img.uploaded_at
            })
        return Response(response_data)