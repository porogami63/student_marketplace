from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Listing, Profile, ForumPost, ForumReply, Transaction, Category, ProfilePost, ProfilePostComment, School, UserReport
import re

# Category-specific product attribute definitions
PRODUCT_ATTRIBUTES = {
    'textbooks': [
        {'field': 'author', 'label': 'Author', 'type': 'text', 'required': True},
        {'field': 'edition', 'label': 'Edition', 'type': 'text', 'required': False},
        {'field': 'isbn', 'label': 'ISBN (if available)', 'type': 'text', 'required': False},
        {'field': 'subject', 'label': 'Subject/Course', 'type': 'text', 'required': True},
    ],
    'electronics': [
        {'field': 'brand', 'label': 'Brand', 'type': 'text', 'required': True},
        {'field': 'model', 'label': 'Model', 'type': 'text', 'required': True},
        {'field': 'storage', 'label': 'Storage (e.g., 256GB, 8GB)', 'type': 'text', 'required': False},
        {'field': 'ram', 'label': 'RAM (if applicable)', 'type': 'text', 'required': False},
        {'field': 'color', 'label': 'Color', 'type': 'text', 'required': False},
        {'field': 'year_purchased', 'label': 'Year Purchased', 'type': 'number', 'required': False},
    ],
    'clothing': [
        {'field': 'school_college', 'label': 'School / College (if uniform)', 'type': 'text', 'required': False},
        {'field': 'uniform_type', 'label': 'Type (e.g., PE Uniform, Lab Coat, Formal)', 'type': 'text', 'required': False},
        {'field': 'gender', 'label': 'For', 'type': 'select', 'options': ['--', 'Male', 'Female', 'Unisex'], 'required': True},
        {'field': 'size', 'label': 'Size', 'type': 'text', 'required': True},
        {'field': 'material', 'label': 'Material (e.g., Cotton, Polyester)', 'type': 'text', 'required': False},
        {'field': 'brand', 'label': 'Brand (if applicable)', 'type': 'text', 'required': False},
    ],
    'supplies': [
        {'field': 'type', 'label': 'Type of Supply', 'type': 'text', 'required': True},
        {'field': 'quantity', 'label': 'Quantity', 'type': 'text', 'required': False},
        {'field': 'brand', 'label': 'Brand', 'type': 'text', 'required': False},
    ],
    'notes': [
        {'field': 'subject', 'label': 'Subject/Course', 'type': 'text', 'required': True},
        {'field': 'semester', 'label': 'Semester (e.g., 1st Sem AY 2024-25)', 'type': 'text', 'required': False},
        {'field': 'professor', 'label': 'Professor Name', 'type': 'text', 'required': False},
    ],
    'furniture': [
        {'field': 'item_type', 'label': 'Type of Furniture', 'type': 'text', 'required': True},
        {'field': 'material', 'label': 'Material', 'type': 'text', 'required': False},
        {'field': 'dimensions', 'label': 'Dimensions (approx)', 'type': 'text', 'required': False},
        {'field': 'delivery_available', 'label': 'Delivery Available', 'type': 'checkbox', 'required': False},
    ],
}


class SchoolSelect(forms.Select):
    """Custom select widget that adds logo data attributes to school options."""
    
    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        
        # Add logo_url as data attribute if school exists
        # value might be a ModelChoiceIteratorValue object, so we need to handle it carefully
        if value:
            try:
                # Try to convert to int - ModelChoiceIteratorValue can be converted
                school_id = int(value) if value else None
                if school_id:
                    school = School.objects.get(pk=school_id)
                    if school.logo_url:
                        option['attrs']['data-logo'] = school.logo_url
            except (TypeError, ValueError, School.DoesNotExist):
                # Silently skip if we can't get the school or convert the value
                pass
        
        return option


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter your email',
        'autocomplete': 'email'
    }))

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add classes and validation attrs to fields
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Username (3-20 characters)',
            'minlength': '3',
            'maxlength': '20',
            'autocomplete': 'username',
            'pattern': '[a-zA-Z0-9_-]+'
        })
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Password (min 8 characters)',
            'minlength': '8'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirm password',
            'minlength': '8'
        })
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if len(username) < 3:
            raise forms.ValidationError('Username must be at least 3 characters long.')
        if len(username) > 20:
            raise forms.ValidationError('Username must be 20 characters or less.')
        if not re.match(r'^[a-zA-Z0-9_-]+$', username):
            raise forms.ValidationError('Username can only contain letters, numbers, hyphens, and underscores.')
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('This email address is already registered.')
        return email


class ProfileRegistrationForm(forms.ModelForm):
    """Form for completing profile during registration."""
    
    class Meta:
        model = Profile
        fields = ['full_name', 'school', 'year_level', 'birthday', 'age', 'phone', 'address', 'contact_info']
        widgets = {
            'full_name': forms.TextInput(attrs={
                'placeholder': 'Enter your full name',
                'class': 'form-control',
                'minlength': '2',
                'maxlength': '120',
                'required': True
            }),
            'school': SchoolSelect(attrs={
                'class': 'form-control',
                'required': True
            }),
            'year_level': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'birthday': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'age': forms.NumberInput(attrs={
                'placeholder': 'E.g., 18',
                'class': 'form-control',
                'min': '10',
                'max': '80'
            }),
            'phone': forms.TextInput(attrs={
                'placeholder': 'Mobile number (e.g., 09123456789)',
                'class': 'form-control',
                'pattern': r'^[0-9+\-\s()]{7,20}$',
                'title': 'Valid phone number',
            }),
            'address': forms.TextInput(attrs={
                'placeholder': 'General meetup area or barangay',
                'class': 'form-control',
                'maxlength': '255',
            }),
            'contact_info': forms.TextInput(attrs={
                'placeholder': 'Social media handles or alternate contact',
                'class': 'form-control',
                'maxlength': '200',
            }),
        }
    
    def clean_full_name(self):
        full_name = self.cleaned_data.get('full_name', '').strip()
        if len(full_name) < 2:
            raise forms.ValidationError('Full name must be at least 2 characters long.')
        if len(full_name) > 120:
            raise forms.ValidationError('Full name must be 120 characters or less.')
        return full_name
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if phone and not re.match(r'^[0-9+\-\s()]{7,20}$', phone):
            raise forms.ValidationError('Enter a valid phone number (7-20 digits/symbols).')
        return phone
    
    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None:
            if age < 10:
                raise forms.ValidationError('You must be at least 10 years old.')
            if age > 80:
                raise forms.ValidationError('Please enter a valid age.')
        return age


class ListingForm(forms.ModelForm):
    class Meta:
        model = Listing
        fields = [
            'listing_type', 'title', 'description', 'price', 'category', 'condition',
            'campus', 'image', 'school', 'contact_info'
        ]
        widgets = {
            'listing_type': forms.RadioSelect(choices=[
                ('wts', 'Want to Sell (WTS) - I have an item to sell'),
                ('wtb', 'Want to Buy (WTB) - I\'m looking for an item to purchase'),
            ], attrs={
                'class': 'form-check-input',
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'What are you selling?',
                'minlength': '5',
                'maxlength': '200',
                'required': True
            }),
            'description': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control',
                'placeholder': 'Describe the condition, features, and why you\'re selling it...',
                'maxlength': '2000',
                'minlength': '10'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '₱0.00',
                'min': '0',
                'max': '999999',
                'step': '0.01',
                'inputmode': 'decimal'
            }),
            'category': forms.Select(attrs={'class': 'form-control category-select', 'id': 'id_category'}),
            'condition': forms.Select(attrs={'class': 'form-control'}),
            'campus': forms.Select(attrs={'class': 'form-control'}),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'school': SchoolSelect(attrs={'class': 'form-control', 'id': 'id_school'}),
            'contact_info': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Phone, email, or social media (optional)',
                'maxlength': '200'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.product_attribute_fields = {}
        
        # Determine listing type from data or instance
        listing_type = None
        if self.data:
            listing_type = self.data.get('listing_type', 'wts')
        elif self.instance and self.instance.listing_type:
            listing_type = self.instance.listing_type
        else:
            listing_type = 'wts'

        # Hide condition field for WTB listings since it's not applicable
        if listing_type == 'wtb':
            if 'condition' in self.fields:
                self.fields['condition'].widget = forms.HiddenInput()

        # Determine category from data or instance
        category = None
        if self.data:
            category_id = self.data.get('category')
            if category_id and (isinstance(category_id, int) or category_id.isdigit()):
                try:
                    category = Category.objects.get(id=category_id)
                except (Category.DoesNotExist, ValueError):
                    pass
        elif self.instance and self.instance.category:
            category = self.instance.category

        if category:
            self._add_product_fields(category.slug)
    
    def _add_product_fields(self, category_slug):
        """Dynamically add product attribute fields based on category."""
        attributes = PRODUCT_ATTRIBUTES.get(category_slug, [])
        existing_values = self.instance.product_details if self.instance.product_details else {}
        
        for attr in attributes:
            field_name = f"product_{attr['field']}"
            initial_value = existing_values.get(attr['field'], '')
            
            if attr['type'] == 'text':
                self.fields[field_name] = forms.CharField(
                    label=attr['label'],
                    required=attr.get('required', False),
                    initial=initial_value if self.data is None else self.data.get(field_name, ''),
                    widget=forms.TextInput(attrs={
                        'class': 'form-control product-field',
                        'data-field': attr['field'],
                        'maxlength': '200'
                    })
                )
            elif attr['type'] == 'number':
                self.fields[field_name] = forms.IntegerField(
                    label=attr['label'],
                    required=attr.get('required', False),
                    initial=initial_value if self.data is None else self.data.get(field_name, ''),
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control product-field',
                        'data-field': attr['field'],
                        'min': '1900',
                        'max': '2100'
                    })
                )
            elif attr['type'] == 'select':
                self.fields[field_name] = forms.ChoiceField(
                    label=attr['label'],
                    choices=[(x, x) for x in attr.get('options', [])],
                    required=attr.get('required', False),
                    initial=initial_value if self.data is None else self.data.get(field_name, ''),
                    widget=forms.Select(attrs={'class': 'form-control product-field', 'data-field': attr['field']})
                )
            elif attr['type'] == 'checkbox':
                self.fields[field_name] = forms.BooleanField(
                    label=attr['label'],
                    required=False,
                    initial=existing_values.get(attr['field'], False) if self.data is None else self.data.get(field_name),
                    widget=forms.CheckboxInput(attrs={'class': 'product-field', 'data-field': attr['field']})
                )
            
            self.product_attribute_fields[field_name] = attr['field']
    
    def clean(self):
        """Extract product details from form fields."""
        cleaned_data = super().clean()
        product_details = {}
        
        # Collect all product_* fields
        for field_name, original_field in self.product_attribute_fields.items():
            value = cleaned_data.get(field_name)
            if value and value != '--':
                product_details[original_field] = str(value)
        
        # Store in a way we can access in save()
        self.product_details = product_details
        return cleaned_data
    
    def clean_title(self):
        title = self.cleaned_data.get('title', '').strip()
        if len(title) < 5:
            raise forms.ValidationError('Title must be at least 5 characters long.')
        if len(title) > 200:
            raise forms.ValidationError('Title must be 200 characters or less.')
        return title
    
    def clean_description(self):
        description = self.cleaned_data.get('description', '').strip()
        if description and len(description) < 10:
            raise forms.ValidationError('Description must be at least 10 characters long.')
        if description and len(description) > 2000:
            raise forms.ValidationError('Description must be 2000 characters or less.')
        return description
    
    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None:
            if price < 0:
                raise forms.ValidationError('Price cannot be negative.')
            if price > 999999:
                raise forms.ValidationError('Price is too high. Maximum is ₱999,999.')
            if price == 0:
                raise forms.ValidationError('Price must be greater than zero.')
        return price
    
    def save(self, commit=True):
        """Save the listing with product details."""
        instance = super().save(commit=False)
        if hasattr(self, 'product_details'):
            instance.product_details = self.product_details
        if commit:
            instance.save()
        return instance


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['full_name', 'school', 'year_level', 'age', 'birthday', 'phone', 'address', 'bio', 'avatar', 'header_image']
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'minlength': '2',
                'maxlength': '120',
            }),
            'address': forms.TextInput(attrs={
                'placeholder': 'e.g. Sampaloc, Manila or near LRT Legarda',
                'class': 'form-control',
                'maxlength': '255',
            }),
            'bio': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'maxlength': '500',
                'placeholder': 'Tell us about yourself (max 500 chars)'
            }),
            'school': SchoolSelect(attrs={'id': 'id_school', 'class': 'form-control'}),
            'birthday': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'age': forms.NumberInput(attrs=
                {'min': 10, 'max': 80, 'class': 'form-control'}),
            'phone': forms.TextInput(attrs={
                'placeholder': 'Mobile number',
                'class': 'form-control',
                'pattern': r'^[0-9+\-\s()]{7,20}$',
                'title': 'Valid phone number'
            }),

            'avatar': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'header_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'year_level': forms.Select(attrs={'class': 'form-control'})
        }
    
    def clean_full_name(self):
        full_name = self.cleaned_data.get('full_name', '').strip()
        if full_name and len(full_name) < 2:
            raise forms.ValidationError('Full name must be at least 2 characters long.')
        if full_name and len(full_name) > 120:
            raise forms.ValidationError('Full name must be 120 characters or less.')
        return full_name
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if phone and not re.match(r'^[0-9+\-\s()]{7,20}$', phone):
            raise forms.ValidationError('Enter a valid phone number.')
        return phone
    
    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None:
            if age < 10:
                raise forms.ValidationError('You must be at least 10 years old.')
            if age > 80:
                raise forms.ValidationError('Please enter a valid age.')
        return age
    
    def clean_bio(self):
        bio = self.cleaned_data.get('bio', '').strip()
        if bio and len(bio) > 500:
            raise forms.ValidationError('Bio must be 500 characters or less.')
        return bio


class MessageForm(forms.Form):
    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Type your message...'}))


class ForumPostForm(forms.ModelForm):
    class Meta:
        model = ForumPost
        fields = ['title', 'body', 'listing']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'What do you want to discuss?',
                'minlength': '5',
                'maxlength': '200',
                'required': True
            }),
            'body': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Share your listing, ask questions, or chat with the community...',
                'class': 'form-control',
                'minlength': '10',
                'maxlength': '5000'
            }),
            'listing': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['listing'].queryset = Listing.objects.filter(seller=user, is_sold=False)
            self.fields['listing'].required = False
            self.fields['listing'].label = 'Link your listing (optional)'
            self.fields['listing'].empty_label = 'None - just a discussion'
    
    def clean_title(self):
        title = self.cleaned_data.get('title', '').strip()
        if len(title) < 5:
            raise forms.ValidationError('Title must be at least 5 characters long.')
        if len(title) > 200:
            raise forms.ValidationError('Title must be 200 characters or less.')
        return title
    
    def clean_body(self):
        body = self.cleaned_data.get('body', '').strip()
        if len(body) < 10:
            raise forms.ValidationError('Post must be at least 10 characters long.')
        if len(body) > 5000:
            raise forms.ValidationError('Post must be 5000 characters or less.')
        return body
    
    def __str__(self):
        return "Forum Post"


class ForumReplyForm(forms.ModelForm):
    class Meta:
        model = ForumReply
        fields = ['body']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Write a reply...'}),
        }

class PurchaseForm(forms.ModelForm):
    """Form for initiating a purchase with exchange method and notes."""
    class Meta:
        model = Transaction
        fields = ['exchange_method', 'notes']
        widgets = {
            'exchange_method': forms.RadioSelect(choices=Transaction.EXCHANGE_METHOD_CHOICES),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Add any notes for the seller (e.g., "Can meet at SM Mall" or "Available after 5pm")',
                'class': 'form-control'
            }),
        }
        labels = {
            'exchange_method': 'How would you like to exchange payment & goods?',
            'notes': 'Message to seller (optional)',
        }


class TransactionConfirmForm(forms.ModelForm):
    """Form for seller to confirm transaction with their notes."""
    class Meta:
        model = Transaction
        fields = ['seller_notes']
        widgets = {
            'seller_notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Confirm availability, location, or other details (e.g., "Available Sat-Sun 2-5pm" or "My number: 09xxxxxxxxx")',
                'class': 'form-control'
            }),
        }
        labels = {
            'seller_notes': 'Your confirmation & meeting details (optional)',
        }


class ProfilePostForm(forms.ModelForm):
    """Form for creating profile posts with optional images."""
    class Meta:
        model = ProfilePost
        fields = ['content', 'image']
        widgets = {
            'content': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Share your thoughts, updates, or messages with visitors to your profile. Max 1000 characters.',
                'class': 'form-control',
                'maxlength': '1000',
                'minlength': '5'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }
        labels = {
            'content': 'What\'s on your mind?',
            'image': 'Add an image (optional)',
        }
    
    def clean_content(self):
        content = self.cleaned_data.get('content', '').strip()
        if len(content) < 5:
            raise forms.ValidationError('Post must be at least 5 characters long.')
        if len(content) > 1000:
            raise forms.ValidationError('Post must be 1000 characters or less.')
        return content


class ProfilePostCommentForm(forms.ModelForm):
    """Form for commenting on profile posts with optional images."""
    class Meta:
        model = ProfilePostComment
        fields = ['content', 'image']
        widgets = {
            'content': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Share a comment or reply... (max 500 characters)',
                'class': 'form-control',
                'maxlength': '500',
                'minlength': '2'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }
        labels = {
            'content': 'Your comment',
            'image': 'Add an image (optional)',
        }
    
    def clean_content(self):
        content = self.cleaned_data.get('content', '').strip()
        if len(content) < 2:
            raise forms.ValidationError('Comment must be at least 2 characters long.')
        if len(content) > 500:
            raise forms.ValidationError('Comment must be 500 characters or less.')
        return content


class ReportForm(forms.ModelForm):
    """Minimal report submission form."""

    class Meta:
        model = UserReport
        fields = ['reason', 'description']
        widgets = {
            'reason': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Add context (optional but helpful). Include dates, what happened, and any screenshots/details you have.',
                'maxlength': '2000',
            }),
        }

    def clean_description(self):
        description = (self.cleaned_data.get('description') or '').strip()
        if len(description) > 2000:
            raise forms.ValidationError('Description is too long (max 2000 characters).')
        return description