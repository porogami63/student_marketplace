# UBXchange
Made by Students for Students 
A Django marketplace for students in the University Belt (U-Belt) area of Manila, Philippines. Buy and sell textbooks, school supplies, electronics, dorm items, and more among students from UST, FEU, UE, San Beda, UP Manila, DLSU, TIP Manila, CEU, LCCM, NTC, and other U-Belt schools.

## Features

- **User accounts** – Register, login, and manage your profile
- **Rich profiles** – Full name, phone, address/meetup area, school, bio, avatar
- **School color coding** – Each school has its official color motif (e.g. UST gold, FEU green & gold)
- **Listings** – Post items with title, description, price, condition, and image
- **Seller details on listings** – Name, contact, school, meetup area displayed to buyers
- **Search & filters** – Filter by category, school, price range
- **Favorites** – Save listings for later
- **View count** – See how many people viewed your listing
- **More from seller** – Browse other items from the same seller
- **Messaging** – Private conversations with sellers (start from any listing)
- **Live Forum** – Community posts to promote listings, discuss, ask questions; link your listings
- **Price statistics** – See how your listing compares to similar items (overpriced / fair / great deal)

## Setup

1. **Create and activate a virtual environment** (recommended):

   ```bash
   python -m venv venv
   venv\Scripts\activate   # Windows
   # or: source venv/bin/activate   # macOS/Linux
   ```

2. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

3. **Run migrations**:

   ```bash
   python manage.py migrate
   ```

4. **Populate schools and categories**:

   ```bash
   python manage.py setup_ubelt
   ```

5. **Create a superuser** (optional, for admin):

   ```bash
   python manage.py createsuperuser
   ```

6. **Run the development server**:

   ```bash
   python manage.py runserver
   ```

7. Open http://127.0.0.1:8000/ in your browser.

## Tech Stack

- Django 4.x
- SQLite (dev; switch to PostgreSQL for production)
- Bootstrap 5
- Pillow (image uploads)
- Crispy Forms
