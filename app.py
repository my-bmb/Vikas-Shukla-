# app.py
import os
import json
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from supabase import create_client, Client
from dotenv import load_dotenv
import pandas as pd
from io import BytesIO

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'active-packers-movers-secret-key-2026'

# Supabase Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL', 'your-supabase-url')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', 'your-supabase-anon-key')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Status choices
STATUS_CHOICES = [
    'New Lead',
    'Contacted',
    'Follow-up Pending',
    'Customer Ready (1 day)',
    'Customer Ready (3 days)',
    'Customer Ready (7 days)',
    'Quotation Sent',
    'Negotiation',
    'Payment Pending',
    'Closed - Won',
    'Closed - Lost'
]

# Source choices
SOURCE_CHOICES = ['Google Adsense', 'Justdial', 'WhatsApp', 'Reference', 'Walk-in']

# Vehicle choices
VEHICLE_CHOICES = ['Small Tata Ace', 'Medium Pickup', 'Large 10ft Truck', '14ft Truck', '17ft Truck', 'Not Assigned Yet']

def get_leads(filters=None):
    """Fetch leads from Supabase with optional filters"""
    try:
        query = supabase.table('leads').select('*').order('created_at', desc=True)
        
        if filters:
            for key, value in filters.items():
                if value and value != 'all':
                    query = query.eq(key, value)
        
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"Error fetching leads: {e}")
        return []

def get_lead_by_id(lead_id):
    """Fetch single lead by ID"""
    try:
        response = supabase.table('leads').select('*').eq('id', lead_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching lead: {e}")
        return None

@app.route('/')
def index():
    # Get all leads
    leads = get_leads()
    
    # Dashboard stats
    all_leads = get_leads()
    total_leads = len(all_leads)
    adsense_leads = len([l for l in all_leads if l.get('source') == 'Google Adsense'])
    justdial_leads = len([l for l in all_leads if l.get('source') == 'Justdial'])
    whatsapp_leads = len([l for l in all_leads if l.get('source') == 'WhatsApp'])
    
    # Today's followups
    today = date.today().isoformat()
    pending_followups = len([l for l in all_leads if l.get('followup_date') == today])
    
    # Revenue stats
    total_revenue = sum([l.get('final_cost', 0) for l in all_leads if l.get('payment_status') == 'Completed'])
    pending_amount = sum([l.get('final_cost', 0) - l.get('advance_paid', 0) for l in all_leads if l.get('payment_status') != 'Completed'])
    
    # Conversion rate
    total_closed = len([l for l in all_leads if l.get('status') in ['Closed - Won', 'Closed - Lost']])
    won_leads = len([l for l in all_leads if l.get('status') == 'Closed - Won'])
    conversion_rate = (won_leads / total_closed * 100) if total_closed > 0 else 0
    
    stats = {
        'total_leads': total_leads,
        'adsense_leads': adsense_leads,
        'justdial_leads': justdial_leads,
        'whatsapp_leads': whatsapp_leads,
        'pending_followups': pending_followups,
        'total_revenue': total_revenue,
        'pending_amount': pending_amount,
        'won_leads': won_leads,
        'conversion_rate': round(conversion_rate, 1)
    }
    
    return render_template('index.html', leads=leads, stats=stats, 
                         statuses=STATUS_CHOICES, sources=SOURCE_CHOICES,
                         vehicles=VEHICLE_CHOICES)

@app.route('/api/leads')
def api_leads():
    """API endpoint to get all leads as JSON"""
    try:
        leads = get_leads()
        return jsonify(leads)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/lead/<int:lead_id>/call_logs')
def api_call_logs(lead_id):
    """API endpoint to get call logs for a specific lead"""
    try:
        lead = get_lead_by_id(lead_id)
        if lead:
            call_history = json.loads(lead.get('call_history', '[]'))
            return jsonify({'call_history': call_history, 'success': True})
        return jsonify({'call_history': [], 'success': False, 'error': 'Lead not found'})
    except Exception as e:
        return jsonify({'call_history': [], 'success': False, 'error': str(e)})

@app.route('/ping')
def ping():
    """Health check endpoint for Cron-job.org to keep the server alive"""
    try:
        # Log the ping request
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[PING] Health check received at {current_time}")
        
        # Check database connection
        test_query = supabase.table('leads').select('id').limit(1).execute()
        
        # Return success response with status
        return jsonify({
            'status': 'active',
            'timestamp': current_time,
            'message': 'Server is running successfully',
            'database': 'connected'
        }), 200
    except Exception as e:
        print(f"[PING] Error: {e}")
        return jsonify({
            'status': 'error',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'message': str(e),
            'database': 'disconnected'
        }), 500

@app.route('/health')
def health():
    """Detailed health check endpoint"""
    try:
        # Check database connection
        db_status = 'connected'
        try:
            supabase.table('leads').select('id').limit(1).execute()
        except:
            db_status = 'disconnected'
        
        leads_count = len(get_leads())
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'database': db_status,
            'leads_count': leads_count,
            'server': 'running',
            'uptime': 'active'
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }), 500

@app.route('/add_lead', methods=['POST'])
def add_lead():
    try:
        # Check for duplicate phone
        phone = request.form.get('phone')
        existing = supabase.table('leads').select('*').eq('phone', phone).execute()
        
        if existing.data:
            flash(f'Duplicate! Phone number {phone} already exists for {existing.data[0]["name"]}', 'danger')
            return redirect(url_for('index'))
        
        # Prepare lead data
        lead_data = {
            'name': request.form.get('name'),
            'phone': phone,
            'alternate_phone': request.form.get('alternate_phone'),
            'source': request.form.get('source'),
            'status': request.form.get('status'),
            'cost_estimate': float(request.form.get('cost_estimate', 0)),
            'final_cost': float(request.form.get('final_cost', 0)),
            'advance_paid': float(request.form.get('advance_paid', 0)),
            'payment_status': request.form.get('payment_status', 'Pending'),
            'from_location': request.form.get('from_location'),
            'to_location': request.form.get('to_location'),
            'distance_km': int(request.form.get('distance_km')) if request.form.get('distance_km') else None,
            'shifting_date': request.form.get('shifting_date') if request.form.get('shifting_date') else None,
            'shifting_time_slot': request.form.get('shifting_time_slot'),
            'vehicle_assigned': request.form.get('vehicle_assigned', 'Not Assigned Yet'),
            'driver_name': request.form.get('driver_name'),
            'driver_phone': request.form.get('driver_phone'),
            'goods_description': request.form.get('goods_description'),
            'fragile_items': request.form.get('fragile_items') == 'on',
            'insurance_required': request.form.get('insurance_required') == 'on',
            'notes': request.form.get('notes'),
            'followup_date': request.form.get('followup_date') if request.form.get('followup_date') else None,
            'followup_notes': request.form.get('followup_notes'),
            'call_history': json.dumps([]),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        # Insert into Supabase
        response = supabase.table('leads').insert(lead_data).execute()
        
        if response.data:
            flash('Lead added successfully!', 'success')
        else:
            flash('Error adding lead!', 'danger')
            
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        print(f"Error adding lead: {e}")
    
    return redirect(url_for('index'))

@app.route('/edit_lead/<int:lead_id>', methods=['POST'])
def edit_lead(lead_id):
    try:
        # Prepare update data
        update_data = {
            'name': request.form.get('name'),
            'phone': request.form.get('phone'),
            'alternate_phone': request.form.get('alternate_phone'),
            'source': request.form.get('source'),
            'status': request.form.get('status'),
            'cost_estimate': float(request.form.get('cost_estimate', 0)),
            'final_cost': float(request.form.get('final_cost', 0)),
            'advance_paid': float(request.form.get('advance_paid', 0)),
            'payment_status': request.form.get('payment_status', 'Pending'),
            'from_location': request.form.get('from_location'),
            'to_location': request.form.get('to_location'),
            'distance_km': int(request.form.get('distance_km')) if request.form.get('distance_km') else None,
            'shifting_date': request.form.get('shifting_date') if request.form.get('shifting_date') else None,
            'shifting_time_slot': request.form.get('shifting_time_slot'),
            'vehicle_assigned': request.form.get('vehicle_assigned', 'Not Assigned Yet'),
            'driver_name': request.form.get('driver_name'),
            'driver_phone': request.form.get('driver_phone'),
            'goods_description': request.form.get('goods_description'),
            'fragile_items': request.form.get('fragile_items') == 'on',
            'insurance_required': request.form.get('insurance_required') == 'on',
            'notes': request.form.get('notes'),
            'followup_date': request.form.get('followup_date') if request.form.get('followup_date') else None,
            'followup_notes': request.form.get('followup_notes'),
            'updated_at': datetime.now().isoformat()
        }
        
        # Update in Supabase
        response = supabase.table('leads').update(update_data).eq('id', lead_id).execute()
        
        if response.data:
            flash('Lead updated successfully!', 'success')
        else:
            flash('Error updating lead!', 'danger')
            
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        print(f"Error editing lead: {e}")
    
    return redirect(url_for('index'))

@app.route('/delete_lead/<int:lead_id>')
def delete_lead(lead_id):
    try:
        response = supabase.table('leads').delete().eq('id', lead_id).execute()
        
        if response.data:
            flash('Lead deleted successfully!', 'success')
        else:
            flash('Error deleting lead!', 'danger')
            
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        print(f"Error deleting lead: {e}")
    
    return redirect(url_for('index'))

@app.route('/add_call_log/<int:lead_id>', methods=['POST'])
def add_call_log(lead_id):
    try:
        call_note = request.form.get('call_note')
        lead = get_lead_by_id(lead_id)
        
        if lead:
            # Get existing call history
            call_history = json.loads(lead.get('call_history', '[]'))
            
            # Add new log
            call_history.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'note': call_note,
                'created_at': datetime.now().isoformat()
            })
            
            # Update in Supabase
            supabase.table('leads').update({
                'call_history': json.dumps(call_history),
                'updated_at': datetime.now().isoformat()
            }).eq('id', lead_id).execute()
            
            # Return JSON response for AJAX calls
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Call log added successfully'})
            
            flash('Call log added successfully!', 'success')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': 'Lead not found'})
            flash('Lead not found!', 'danger')
            
    except Exception as e:
        error_msg = f'Error: {str(e)}'
        print(f"Error adding call log: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error_msg})
        flash(error_msg, 'danger')
    
    # For regular form submissions, redirect back
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return redirect(url_for('index'))
    
    return jsonify({'success': True})

@app.route('/export_excel')
def export_excel():
    try:
        leads = get_leads()
        
        # Convert to DataFrame
        df = pd.DataFrame(leads)
        
        # Select relevant columns
        columns = ['id', 'name', 'phone', 'source', 'status', 'cost_estimate', 'final_cost', 
                  'advance_paid', 'payment_status', 'from_location', 'to_location', 
                  'shifting_date', 'created_at', 'notes']
        
        df = df[[col for col in columns if col in df.columns]]
        
        # Create Excel file
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Leads', index=False)
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'leads_export_{datetime.now().strftime("%Y%m%d")}.xlsx'
        )
        
    except Exception as e:
        flash(f'Error exporting: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/search')
def search():
    query = request.args.get('q', '')
    
    try:
        # Search in Supabase
        results = supabase.table('leads').select('*')\
            .or_(f"name.ilike.%{query}%,phone.ilike.%{query}%,from_location.ilike.%{query}%,to_location.ilike.%{query}%")\
            .execute()
        
        leads = results.data
        
        # Return JSON for AJAX search
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(leads)
        
        return render_template('index.html', leads=leads, stats={}, 
                             statuses=STATUS_CHOICES, sources=SOURCE_CHOICES,
                             vehicles=VEHICLE_CHOICES, search_query=query)
                             
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify([]) if request.headers.get('X-Requested-With') == 'XMLHttpRequest' else redirect(url_for('index'))

@app.route('/filter_by_status/<status>')
def filter_by_status(status):
    leads = get_leads({'status': status}) if status != 'all' else get_leads()
    return render_template('index.html', leads=leads, stats={}, 
                         statuses=STATUS_CHOICES, sources=SOURCE_CHOICES,
                         vehicles=VEHICLE_CHOICES, current_status=status)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
