from rest_framework.routers import DefaultRouter
from .views import VisitorViewSet, VisitorPassViewSet

router = DefaultRouter()
router.register("visitors", VisitorViewSet, basename="visitor")
router.register("visitor-passes", VisitorPassViewSet, basename="visitor-pass")

urlpatterns = router.urls
