from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import Group, Permission
from .models import User

@receiver(post_save, sender=User)
def assign_user_permissions(sender, instance, created, **kwargs):
    """Assign appropriate permissions based on user role"""
    if created:
        # Assign default role-based permissions
        # This would be expanded based on the role
        pass

@receiver(post_save, sender=User)
def create_user_activity_log(sender, instance, created, **kwargs):
    """Create activity log for new user creation"""
    if created:
        # This is handled in the registration view
        pass