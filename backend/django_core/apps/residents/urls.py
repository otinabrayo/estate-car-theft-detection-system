from rest_framework.routers import DefaultRouter

from .views import ResidentViewSet

router = DefaultRouter()
router.register("residents", ResidentViewSet, basename="resident")

urlpatterns = router.urls
