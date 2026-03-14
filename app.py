from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json
import os

app = Flask(__name__)

# Database configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'duozo-inventory-secret-key-2026'  # For session management

db = SQLAlchemy(app)

# =====================
# DATABASE MODELS
# =====================

class Outlet(db.Model):
    """Represents a retail outlet/store location"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    city = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(255))
    manager_name = db.Column(db.String(100))
    manager_phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    inventory = db.relationship('Inventory', backref='outlet', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'city': self.city,
            'address': self.address,
            'manager_name': self.manager_name,
            'manager_phone': self.manager_phone
        }

class Item(db.Model):
    """Represents a product/item (e.g., 1kg Sweet Box, 250ml Bowl)"""
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    unit = db.Column(db.String(50))  # e.g., "piece", "box", "carton"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    inventory = db.relationship('Inventory', backref='item', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'sku': self.sku,
            'name': self.name,
            'description': self.description,
            'unit': self.unit
        }

class Location(db.Model):
    """Represents a physical location within an outlet (e.g., Store Room, Rack 3, Shelf B)"""
    id = db.Column(db.Integer, primary_key=True)
    outlet_id = db.Column(db.Integer, db.ForeignKey('outlet.id'), nullable=False)
    store_room = db.Column(db.String(100), nullable=False)  # e.g., "Main Store Room", "Packing Room"
    rack_number = db.Column(db.String(50), nullable=False)   # e.g., "Rack 1", "Rack 3"
    shelf = db.Column(db.String(50), nullable=False)         # e.g., "Shelf A", "Shelf B"
    bin = db.Column(db.String(50))                           # e.g., "Bin 1", optional
    
    outlet_rel = db.relationship('Outlet', backref='locations')
    inventory = db.relationship('Inventory', backref='location', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'outlet_id': self.outlet_id,
            'store_room': self.store_room,
            'rack_number': self.rack_number,
            'shelf': self.shelf,
            'bin': self.bin
        }
    
    def get_address(self):
        """Returns formatted physical location string"""
        location = f"{self.store_room}, {self.rack_number}, {self.shelf}"
        if self.bin:
            location += f", {self.bin}"
        return location

class Inventory(db.Model):
    """Tracks quantity of items at specific locations in specific outlets"""
    id = db.Column(db.Integer, primary_key=True)
    outlet_id = db.Column(db.Integer, db.ForeignKey('outlet.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    safety_stock_level = db.Column(db.Integer, default=50)  # Alert threshold
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    alerts = db.relationship('StockAlert', backref='inventory_record', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        is_low_stock = self.quantity < self.safety_stock_level
        return {
            'id': self.id,
            'outlet_id': self.outlet_id,
            'outlet_name': self.outlet.name,
            'item_id': self.item_id,
            'item_name': self.item.name,
            'item_sku': self.item.sku,
            'location_id': self.location_id,
            'location': self.location.get_address(),
            'quantity': self.quantity,
            'safety_stock_level': self.safety_stock_level,
            'is_low_stock': is_low_stock,
            'last_updated': self.last_updated.isoformat()
        }

class StockAlert(db.Model):
    """Tracks low-stock alerts triggered for items"""
    id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('inventory.id'), nullable=False)
    alert_type = db.Column(db.String(50))  # "low_stock", "out_of_stock"
    message = db.Column(db.Text)
    is_resolved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    
    def to_dict(self):
        return {
            'id': self.id,
            'inventory_id': self.inventory_id,
            'item_name': self.inventory_record.item.name,
            'outlet_name': self.inventory_record.outlet.name,
            'alert_type': self.alert_type,
            'message': self.message,
            'is_resolved': self.is_resolved,
            'created_at': self.created_at.isoformat(),
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None
        }

# =====================
# HELPER FUNCTIONS
# =====================

def check_and_create_alerts(inventory_record):
    """Check if stock is low and create alerts if necessary"""
    if inventory_record.quantity < inventory_record.safety_stock_level:
        # Check if alert already exists
        existing_alert = StockAlert.query.filter_by(
            inventory_id=inventory_record.id,
            is_resolved=False
        ).first()
        
        if not existing_alert:
            if inventory_record.quantity == 0:
                alert_type = "out_of_stock"
                message = f"❌ OUT OF STOCK: {inventory_record.item.name} at {inventory_record.outlet.name}"
            else:
                alert_type = "low_stock"
                message = f"⚠️ LOW STOCK ALERT: {inventory_record.item.name} ({inventory_record.quantity} units) at {inventory_record.outlet.name}. Safety level: {inventory_record.safety_stock_level}"
            
            alert = StockAlert(
                inventory_id=inventory_record.id,
                alert_type=alert_type,
                message=message
            )
            db.session.add(alert)
            db.session.commit()
            return alert
    return None

# =====================
# ROUTES - FRONTEND
# =====================

@app.route('/')
def index():
    """Main landing page - redirect to login or dashboard"""
    if 'outlet_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Manager login page"""
    if request.method == 'POST':
        outlet_name = request.form.get('outlet_name', '')
        password = request.form.get('password', '')
        
        # Simple authentication - in production, use proper password hashing
        outlets_creds = {
            'Nehru Place': 'nehru123',
            'Lajpat Nagar': 'lajpat123',
            'South Extension': 'south123'
        }
        
        if outlet_name in outlets_creds and outlets_creds[outlet_name] == password:
            outlet = Outlet.query.filter_by(name=outlet_name).first()
            if outlet:
                session['outlet_id'] = outlet.id
                session['outlet_name'] = outlet.name
                session['manager_name'] = outlet.manager_name
                return redirect(url_for('dashboard'))
        
        return render_template('login.html', error='Invalid outlet name or password')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Manager logout"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    """Main dashboard page - requires login"""
    if 'outlet_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', outlet_name=session.get('outlet_name'))

@app.route('/get-outlet-info')
def get_outlet_info():
    """Get current outlet and manager info"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    return jsonify({
        'outlet_id': session['outlet_id'],
        'outlet_name': session.get('outlet_name'),
        'manager_name': session.get('manager_name')
    })

# =====================
# API ROUTES - ITEMS
# =====================

@app.route('/api/items', methods=['GET'])
def get_items():
    """Get all items"""
    items = Item.query.all()
    return jsonify([item.to_dict() for item in items])

@app.route('/api/items', methods=['POST'])
def create_item():
    """Create a new item"""
    data = request.get_json()
    
    item = Item(
        sku=data.get('sku'),
        name=data.get('name'),
        description=data.get('description'),
        unit=data.get('unit', 'piece')
    )
    
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201

# =====================
# API ROUTES - OUTLETS
# =====================

@app.route('/api/outlets', methods=['GET'])
def get_outlets():
    """Get all outlets"""
    outlets = Outlet.query.all()
    return jsonify([outlet.to_dict() for outlet in outlets])

@app.route('/api/outlets', methods=['POST'])
def create_outlet():
    """Create a new outlet"""
    data = request.get_json()
    
    outlet = Outlet(
        name=data.get('name'),
        city=data.get('city'),
        address=data.get('address'),
        manager_name=data.get('manager_name'),
        manager_phone=data.get('manager_phone')
    )
    
    db.session.add(outlet)
    db.session.commit()
    return jsonify(outlet.to_dict()), 201

# =====================
# API ROUTES - LOCATIONS
# =====================

@app.route('/api/locations/outlet/<int:outlet_id>', methods=['GET'])
def get_outlet_locations(outlet_id):
    """Get all locations in an outlet"""
    locations = Location.query.filter_by(outlet_id=outlet_id).all()
    return jsonify([loc.to_dict() for loc in locations])

@app.route('/api/locations', methods=['POST'])
def create_location():
    """Create a new location"""
    data = request.get_json()
    
    location = Location(
        outlet_id=data.get('outlet_id'),
        store_room=data.get('store_room'),
        rack_number=data.get('rack_number'),
        shelf=data.get('shelf'),
        bin=data.get('bin')
    )
    
    db.session.add(location)
    db.session.commit()
    return jsonify(location.to_dict()), 201

# =====================
# API ROUTES - INVENTORY
# =====================

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    """Get inventory for manager's outlet"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    inventory = Inventory.query.filter_by(outlet_id=session['outlet_id']).all()
    return jsonify([inv.to_dict() for inv in inventory])

@app.route('/api/inventory/outlet/<int:outlet_id>', methods=['GET'])
def get_outlet_inventory(outlet_id):
    """Get inventory for a specific outlet"""
    inventory = Inventory.query.filter_by(outlet_id=outlet_id).all()
    return jsonify([inv.to_dict() for inv in inventory])

@app.route('/api/inventory/search', methods=['GET'])
def search_inventory():
    """FEATURE 1: Find It - Search for items and get their location"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    query = request.args.get('q', '').lower()
    search_all = request.args.get('search_all', 'false').lower() == 'true'
    
    results = []
    
    if query:
        # Search items by name or SKU
        items = Item.query.filter(
            (Item.name.ilike(f'%{query}%')) | 
            (Item.sku.ilike(f'%{query}%'))
        ).all()
        
        for item in items:
            if search_all:
                # Search across all outlets (for inter-store search)
                inv_records = Inventory.query.filter_by(item_id=item.id).all()
            else:
                # Search only in current manager's outlet
                inv_records = Inventory.query.filter_by(
                    item_id=item.id,
                    outlet_id=session['outlet_id']
                ).all()
            
            for inv in inv_records:
                results.append(inv.to_dict())
    
    return jsonify(results)

@app.route('/api/inventory/update-quantity/<int:inventory_id>/<action>', methods=['PUT'])
def update_inventory_quantity(inventory_id, action):
    """Update inventory quantity with +/- buttons"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    inventory = Inventory.query.get(inventory_id)
    if not inventory:
        return jsonify({'error': 'Inventory record not found'}), 404
    
    # Only manager of that outlet can update
    if inventory.outlet_id != session['outlet_id']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if action == 'increment':
        inventory.quantity += 1
    elif action == 'decrement':
        if inventory.quantity > 0:
            inventory.quantity -= 1
    else:
        return jsonify({'error': 'Invalid action'}), 400
    
    db.session.commit()
    
    # Check for low-stock alerts
    check_and_create_alerts(inventory)
    
    return jsonify(inventory.to_dict())

@app.route('/api/inventory/<int:inventory_id>', methods=['PUT'])
def update_inventory(inventory_id):
    """Update inventory quantity and check for low stock"""
    inventory = Inventory.query.get(inventory_id)
    if not inventory:
        return jsonify({'error': 'Inventory record not found'}), 404
    
    data = request.get_json()
    inventory.quantity = data.get('quantity', inventory.quantity)
    inventory.safety_stock_level = data.get('safety_stock_level', inventory.safety_stock_level)
    
    db.session.commit()
    
    # FEATURE 2: Check for low-stock alerts
    check_and_create_alerts(inventory)
    
    return jsonify(inventory.to_dict())

@app.route('/api/inventory', methods=['POST'])
def create_inventory():
    """Create new product inventory in manager's outlet"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    
    # Validate required fields
    item_sku = data.get('item_sku', '').upper().strip()
    item_name = data.get('item_name', '').strip()
    location_name = data.get('location_name', '').strip()  # e.g., "Rack 3 Shelf B"
    
    if not item_sku or not item_name or not location_name:
        return jsonify({'error': 'Item SKU, name, and location required'}), 400
    
    # Check if item already exists
    item = Item.query.filter_by(sku=item_sku).first()
    if not item:
        item = Item(
            sku=item_sku,
            name=item_name,
            description=data.get('item_description', ''),
            unit=data.get('unit', 'piece')
        )
        db.session.add(item)
        db.session.commit()
    
    # Parse location string and create/get location
    # Expected format: "Rack 3 Shelf B" or similar
    store_room = "Main Store Room"
    parts = location_name.split()
    
    rack_number = "Rack 1"
    shelf = "Shelf A"
    
    if len(parts) >= 2 and parts[0].lower() == "rack":
        rack_number = f"Rack {parts[1]}"
    if len(parts) >= 4 and parts[2].lower() == "shelf":
        shelf = f"Shelf {parts[3]}"
    
    location = Location.query.filter_by(
        outlet_id=session['outlet_id'],
        store_room=store_room,
        rack_number=rack_number,
        shelf=shelf
    ).first()
    
    if not location:
        location = Location(
            outlet_id=session['outlet_id'],
            store_room=store_room,
            rack_number=rack_number,
            shelf=shelf
        )
        db.session.add(location)
        db.session.commit()
    
    # Check if inventory already exists for this item location combo
    existing_inv = Inventory.query.filter_by(
        outlet_id=session['outlet_id'],
        item_id=item.id,
        location_id=location.id
    ).first()
    
    if existing_inv:
        return jsonify({'error': 'This item already exists at this location'}), 400
    
    # Create inventory record
    inventory = Inventory(
        outlet_id=session['outlet_id'],
        item_id=item.id,
        location_id=location.id,
        quantity=int(data.get('quantity', 0)),
        safety_stock_level=int(data.get('safety_stock_level', 50))
    )
    
    db.session.add(inventory)
    db.session.commit()
    
    check_and_create_alerts(inventory)
    
    return jsonify(inventory.to_dict()), 201

@app.route('/api/inventory/<int:inventory_id>', methods=['DELETE'])
def delete_inventory(inventory_id):
    """Delete/remove product from inventory"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    inventory = Inventory.query.get(inventory_id)
    if not inventory:
        return jsonify({'error': 'Inventory record not found'}), 404
    
    # Only manager of that outlet can delete
    if inventory.outlet_id != session['outlet_id']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    item_name = inventory.item.name
    db.session.delete(inventory)
    db.session.commit()
    
    return jsonify({'message': f'{item_name} removed from inventory'}), 200

# =====================
# API ROUTES - ALERTS
# =====================

@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    """FEATURE 2: Get all active low-stock alerts for manager's outlet"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    alerts = StockAlert.query.join(Inventory).filter(
        Inventory.outlet_id == session['outlet_id'],
        StockAlert.is_resolved == False
    ).all()
    return jsonify([alert.to_dict() for alert in alerts])

@app.route('/api/alerts/outlet/<int:outlet_id>', methods=['GET'])
def get_outlet_alerts(outlet_id):
    """Get alerts for a specific outlet"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    alerts = StockAlert.query.join(Inventory).filter(
        Inventory.outlet_id == outlet_id,
        StockAlert.is_resolved == False
    ).all()
    return jsonify([alert.to_dict() for alert in alerts])

@app.route('/api/alerts/<int:alert_id>/resolve', methods=['PUT'])
def resolve_alert(alert_id):
    """Mark an alert as resolved"""
    alert = StockAlert.query.get(alert_id)
    if not alert:
        return jsonify({'error': 'Alert not found'}), 404
    
    alert.is_resolved = True
    alert.resolved_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify(alert.to_dict())

# =====================
# API ROUTES - FEATURE 3: INTER-STORE GRID
# =====================

@app.route('/api/grid/search', methods=['GET'])
def grid_search():
    """FEATURE 3: Inter-Store Grid - Search for item availability across OTHER outlets"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    query = request.args.get('q', '').lower()
    
    if not query:
        return jsonify([])
    
    # Find all instances of the item across ALL outlets
    items = Item.query.filter(
        (Item.name.ilike(f'%{query}%')) | 
        (Item.sku.ilike(f'%{query}%'))
    ).all()
    
    grid_results = []
    for item in items:
        # Show inventory at OTHER outlets (not their own)
        inv_records = Inventory.query.filter(
            Inventory.item_id == item.id,
            Inventory.outlet_id != session['outlet_id']  # Exclude their own outlet
        ).all()
        for inv in inv_records:
            grid_results.append({
                'outlet': inv.outlet.to_dict(),
                'item': inv.item.to_dict(),
                'location': inv.location.get_address(),
                'quantity': inv.quantity,
                'available': inv.quantity > 0,
                'is_low_stock': inv.quantity < inv.safety_stock_level
            })
    
    return jsonify(grid_results)

@app.route('/api/grid/outlets', methods=['GET'])
def get_grid_outlets():
    """Get all OTHER outlets with their inventory summary"""
    if 'outlet_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    outlets = Outlet.query.filter(Outlet.id != session['outlet_id']).all()
    grid_data = []
    
    for outlet in outlets:
        inventory = Inventory.query.filter_by(outlet_id=outlet.id).all()
        low_stock_count = sum(1 for inv in inventory if inv.quantity < inv.safety_stock_level)
        out_of_stock_count = sum(1 for inv in inventory if inv.quantity == 0)
        
        grid_data.append({
            'outlet': outlet.to_dict(),
            'total_items': len(inventory),
            'low_stock_count': low_stock_count,
            'out_of_stock_count': out_of_stock_count
        })
    
    return jsonify(grid_data)

# =====================
# DATABASE INITIALIZATION
# =====================

def init_db():
    """Initialize the database with sample data"""
    with app.app_context():
        db.create_all()
        
        # Check if data already exists
        if Outlet.query.first():
            return
        
        # Create outlets
        outlet1 = Outlet(
            name='Nehru Place',
            city='Delhi',
            address='Nehru Place Market, Delhi',
            manager_name='Raj Kumar',
            manager_phone='9876543210'
        )
        outlet2 = Outlet(
            name='Lajpat Nagar',
            city='Delhi',
            address='Lajpat Nagar, Delhi',
            manager_name='Priya Singh',
            manager_phone='9876543211'
        )
        outlet3 = Outlet(
            name='South Extension',
            city='Delhi',
            address='South Extension, Delhi',
            manager_name='Vikram Patel',
            manager_phone='9876543212'
        )
        
        db.session.add_all([outlet1, outlet2, outlet3])
        db.session.commit()
        
        # Create items
        item1 = Item(sku='BOX-1KG-SWEET', name='1kg Sweet Box', unit='piece')
        item2 = Item(sku='BOWL-250ML', name='250ml Bowl', unit='piece')
        item3 = Item(sku='SPOON-PLASTIC', name='Plastic Spoon', unit='pack')
        item4 = Item(sku='BOX-500G', name='500g Box', unit='piece')
        item5 = Item(sku='NAPKIN-50PC', name='Napkin Pack (50pc)', unit='pack')
        
        db.session.add_all([item1, item2, item3, item4, item5])
        db.session.commit()
        
        # Create locations for each outlet
        for outlet in [outlet1, outlet2, outlet3]:
            loc1 = Location(outlet_id=outlet.id, store_room='Main Store Room', rack_number='Rack 1', shelf='Shelf A')
            loc2 = Location(outlet_id=outlet.id, store_room='Main Store Room', rack_number='Rack 1', shelf='Shelf B')
            loc3 = Location(outlet_id=outlet.id, store_room='Packing Room', rack_number='Rack 2', shelf='Shelf A')
            loc4 = Location(outlet_id=outlet.id, store_room='Back Store', rack_number='Rack 3', shelf='Shelf B', bin='Bin 1')
            
            db.session.add_all([loc1, loc2, loc3, loc4])
        
        db.session.commit()
        
        # Create sample inventory - Nehru Place
        locations_n = Location.query.filter_by(outlet_id=outlet1.id).all()
        inv1 = Inventory(outlet_id=outlet1.id, item_id=item1.id, location_id=locations_n[0].id, quantity=150, safety_stock_level=50)
        inv2 = Inventory(outlet_id=outlet1.id, item_id=item2.id, location_id=locations_n[1].id, quantity=30, safety_stock_level=50)  # Low stock!
        inv3 = Inventory(outlet_id=outlet1.id, item_id=item3.id, location_id=locations_n[2].id, quantity=200, safety_stock_level=100)
        inv4 = Inventory(outlet_id=outlet1.id, item_id=item4.id, location_id=locations_n[3].id, quantity=0, safety_stock_level=50)  # Out of stock!
        inv5 = Inventory(outlet_id=outlet1.id, item_id=item5.id, location_id=locations_n[0].id, quantity=75, safety_stock_level=50)
        
        db.session.add_all([inv1, inv2, inv3, inv4, inv5])
        db.session.commit()
        
        # Create sample inventory - Lajpat Nagar
        locations_l = Location.query.filter_by(outlet_id=outlet2.id).all()
        inv6 = Inventory(outlet_id=outlet2.id, item_id=item1.id, location_id=locations_l[0].id, quantity=200, safety_stock_level=50)
        inv7 = Inventory(outlet_id=outlet2.id, item_id=item2.id, location_id=locations_l[1].id, quantity=120, safety_stock_level=50)
        inv8 = Inventory(outlet_id=outlet2.id, item_id=item3.id, location_id=locations_l[2].id, quantity=15, safety_stock_level=100)  # Low stock!
        inv9 = Inventory(outlet_id=outlet2.id, item_id=item4.id, location_id=locations_l[3].id, quantity=85, safety_stock_level=50)
        inv10 = Inventory(outlet_id=outlet2.id, item_id=item5.id, location_id=locations_l[0].id, quantity=40, safety_stock_level=50)  # Low stock!
        
        db.session.add_all([inv6, inv7, inv8, inv9, inv10])
        db.session.commit()
        
        # Create sample inventory - South Extension
        locations_s = Location.query.filter_by(outlet_id=outlet3.id).all()
        inv11 = Inventory(outlet_id=outlet3.id, item_id=item1.id, location_id=locations_s[0].id, quantity=90, safety_stock_level=50)
        inv12 = Inventory(outlet_id=outlet3.id, item_id=item2.id, location_id=locations_s[1].id, quantity=180, safety_stock_level=50)
        inv13 = Inventory(outlet_id=outlet3.id, item_id=item3.id, location_id=locations_s[2].id, quantity=250, safety_stock_level=100)
        inv14 = Inventory(outlet_id=outlet3.id, item_id=item4.id, location_id=locations_s[3].id, quantity=120, safety_stock_level=50)
        inv15 = Inventory(outlet_id=outlet3.id, item_id=item5.id, location_id=locations_s[0].id, quantity=60, safety_stock_level=50)
        
        db.session.add_all([inv11, inv12, inv13, inv14, inv15])
        db.session.commit()
        
        # Trigger alerts for low stock items
        all_inventory = Inventory.query.all()
        for inv in all_inventory:
            check_and_create_alerts(inv)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', debug=True, port=5000)
