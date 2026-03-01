from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Listing, Profile, ForumPost, ForumReply, Transaction, Category, ProfilePost, School

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
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')


class ProfileRegistrationForm(forms.ModelForm):
    """Form for completing profile during registration."""
    
    class Meta:
        model = Profile
        fields = ['full_name', 'school', 'year_level', 'birthday', 'age', 'phone', 'address', 'contact_info']
        widgets = {
            'full_name': forms.TextInput(attrs={
                'placeholder': 'Enter your full name',
                'class': 'form-control',
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
                'placeholder': 'Mobile number',
                'class': 'form-control',
            }),
            'address': forms.TextInput(attrs={
                'placeholder': 'General meetup area or barangay',
                'class': 'form-control',
            }),
            'contact_info': forms.TextInput(attrs={
                'placeholder': 'Social media handles or alternate contact',
                'class': 'form-control',
            }),
        }


class ListingForm(forms.ModelForm):
    class Meta:
        model = Listing
        fields = [
            'title', 'description', 'price', 'category', 'condition',
            'campus', 'image', 'school', 'contact_info'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'category': forms.Select(attrs={'class': 'category-select', 'id': 'id_category'}),
            'school': SchoolSelect(attrs={'id': 'id_school'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.product_attribute_fields = {}
        
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
                    widget=forms.TextInput(attrs={'class': 'form-control product-field', 'data-field': attr['field']})
                )
            elif attr['type'] == 'number':
                self.fields[field_name] = forms.IntegerField(
                    label=attr['label'],
                    required=attr.get('required', False),
                    initial=initial_value if self.data is None else self.data.get(field_name, ''),
                    widget=forms.NumberInput(attrs={'class': 'form-control product-field', 'data-field': attr['field']})
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
        fields = ['full_name', 'school', 'year_level', 'age', 'birthday', 'phone', 'contact_info', 'address', 'bio', 'avatar', 'header_image']
        widgets = {
            'address': forms.TextInput(attrs={'placeholder': 'e.g. Sampaloc, Manila or near LRT Legarda'}),
            'bio': forms.Textarea(attrs={'rows': 3}),
            'school': SchoolSelect(attrs={'id': 'id_school'}),
            'birthday': forms.DateInput(attrs={'type': 'date'}),
            'age': forms.NumberInput(attrs={'min': 10, 'max': 80}),
        }


class MessageForm(forms.Form):
    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Type your message...'}))


class ForumPostForm(forms.ModelForm):
    class Meta:
        model = ForumPost
        fields = ['title', 'body', 'listing']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Share your listing, ask questions, or chat with the community...'}),
            'listing': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['listing'].queryset = Listing.objects.filter(seller=user, is_sold=False)
            self.fields['listing'].required = False
            self.fields['listing'].label = 'Link your listing (optional)'
            self.fields['listing'].empty_label = 'None - just a discussion'
    
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
    """Form for creating profile posts."""
    class Meta:
        model = ProfilePost
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Share your thoughts, updates, or messages with visitors to your profile. Max 1000 characters.',
                'class': 'form-control',
                'maxlength': '1000'
            }),
        }
        labels = {
            'content': 'What\'s on your mind?',
        }