from rest_framework.routers import DefaultRouter

from .views import SecurityAlertViewSet

router = DefaultRouter()
router.register(
    "security-alerts",
    SecurityAlertViewSet,
    basename="security-alert",
)

urlpatterns = router.urls
