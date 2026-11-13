from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from .models import Employee, WorkHours, AdvancePayment, Salary
import datetime
from PIL import Image
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile

class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username',
            'autofocus': True,
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password',
        })
    )


class EmployeeForm(forms.ModelForm):
    daily_rate = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'readonly': 'readonly', 'id': 'id_daily_rate'})
    )
    hourly_rate = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'readonly': 'readonly', 'id': 'id_hourly_rate'})
    )

    class Meta:
        model = Employee
        fields = ['photo', 'name', 'phone', 'address', 'designation', 'monthly_salary', 'joining_date', 'is_active']
        widgets = {
            'photo': forms.FileInput(attrs={'class': 'form-control', 'accept': '.jpg,.jpeg,.png,.webp', 'id': 'id_photo'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '10-digit phone'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Full Address'}),
            'designation': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Packer, Supervisor'}),
            'monthly_salary': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00', 'step': '0.01', 'id': 'id_monthly_salary'}),
            'joining_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if photo:
            # Check extension
            if not photo.name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                raise forms.ValidationError("Only JPG, JPEG, PNG, or WebP images are accepted.")
                
            # Check 250KB limit
            if photo.size > 250 * 1024:
                raise forms.ValidationError("Image file exceeds 250KB limit.")
                
            # Resize and compress
            try:
                img = Image.open(photo)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                img.thumbnail((300, 300), Image.Resampling.LANCZOS)
                
                output = BytesIO()
                img.save(output, format='JPEG', quality=85, optimize=True)
                output.seek(0)
                output.seek(0, 2)
                size = output.tell()
                output.seek(0)
                
                photo = InMemoryUploadedFile(
                    output,
                    'ImageField',
                    "%s.jpg" % photo.name.split('.')[0],
                    'image/jpeg',
                    size,
                    None
                )
            except Exception as e:
                raise forms.ValidationError(f"Invalid image file: {str(e)}")
                
        return photo

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['daily_rate'].initial = self.instance.daily_rate
            self.fields['hourly_rate'].initial = self.instance.hourly_rate


class WorkHoursDateForm(forms.Form):
    date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        initial=datetime.date.today
    )


class WorkHoursForm(forms.ModelForm):
    class Meta:
        model = WorkHours
        fields = ['employee', 'date', 'hours_worked']
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'hours_worked': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Employee.objects.filter(is_active=True).order_by('name')
        if self.instance and self.instance.pk and self.instance.employee:
            queryset = queryset | Employee.objects.filter(pk=self.instance.employee.pk)
        self.fields['employee'].queryset = queryset


class AdvancePaymentForm(forms.ModelForm):
    class Meta:
        model = AdvancePayment
        fields = ['employee', 'amount', 'date']
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00', 'step': '0.01'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Employee.objects.filter(is_active=True).order_by('name')
        if self.instance and self.instance.pk and self.instance.employee:
            queryset = queryset | Employee.objects.filter(pk=self.instance.employee.pk)
        self.fields['employee'].queryset = queryset


class ManagerForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
        min_length=8
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'})
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm = cleaned_data.get('confirm_password')
        if password and confirm and password != confirm:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.is_staff = True
        if commit:
            user.save()
        return user
