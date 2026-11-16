from rest_framework.routers import DefaultRouter

from .views import VehicleViewSet, AuthorizedDriverViewSet

router = DefaultRouter()

router.register("vehicles", VehicleViewSet, basename="vehicle")

router.register(
    "authorized-drivers",
    AuthorizedDriverViewSet,
    basename="authorized-driver",
)

urlpatterns = router.urls
