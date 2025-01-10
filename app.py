from flask import Flask, render_template, request, redirect, url_for, flash, session,send_file
from flask_mysqldb import MySQL
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from docx import Document
from docx.shared import Pt
import docx2pdf
from io import BytesIO
from datetime import datetime, timedelta
import yaml
import pythoncom
import os
from werkzeug.utils import secure_filename
from collections import deque
import os
import pandas as pd
import locale


app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')

# Database configuration
with open('db.yaml', 'r') as db_file:
    db_config = yaml.safe_load(db_file)

app.config['MYSQL_HOST'] = db_config['mysql_host']
app.config['MYSQL_USER'] = db_config['mysql_user']
app.config['MYSQL_PASSWORD'] = db_config['mysql_password']
app.config['MYSQL_DB'] = db_config['mysql_db']

mysql = MySQL(app)
# Flask-Login configuration
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Redirect to the 'login' route if not authenticated

# User class
class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

# User loader function for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT id, username, role FROM staff WHERE id = %s", [user_id])
    user = cursor.fetchone()
    if user:
        return User(id=user[0], username=user[1], role=user[2])
    return None

@app.route('/')
@login_required
def index():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM staff")
    total_staff = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT staff_id) FROM attendance WHERE DATE(checkin_time) = CURDATE()")
    checked_in_today = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(id) FROM department")
    department_count = cursor.fetchone()[0]
    return render_template('index.html', total_staff=total_staff, present_today=checked_in_today, department_count=department_count)
   
@app.route('/mannage_staff')
@login_required
def admin():
    cursor = mysql.connection.cursor()
    cursor.execute("""
    SELECT 
        s.id, 
        s.name,
        s.position, 
        d.name AS department FROM staff s
    LEFT JOIN department d ON s.department = d.id
""")
    staff_list = cursor.fetchall()
    return render_template('mannage_staff.html', staff_list=staff_list)

@app.route('/onboard', methods=['GET'])
@login_required
def onboard():
    # Fetch all existing staff for the dropdown
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT id, name FROM staff")
    staff_list = cursor.fetchall()  # Returns a list of tuples [(id1, name1), (id2, name2), ...]
    cursor.execute("SELECT id, name FROM department")
    department_list = cursor.fetchall()
    return render_template('onboard.html', staff_list=staff_list, department_list=department_list)

@app.route('/add_staff', methods=['POST'])
@login_required
def add_staff():
    if request.method == 'POST':
        name = request.form['name']
        department = request.form['department']
        reportee = request.form['reportee']
        email = request.form['email']
        positon = request.form['position']
        
        if name and department and reportee and email:
            cursor = mysql.connection.cursor()
            # Insert new staff into the staff table
            cursor.execute(
                "INSERT INTO staff (name, department, reportee, email, position) VALUES (%s, %s, %s, %s, %s)",
                (name, department, reportee, email, positon)
            )
            mysql.connection.commit()
            flash('Staff added successfully!', 'success')
        else:
            flash('Please fill in all fields.', 'danger')
        
        return redirect(url_for('admin'))


@app.route('/edit_staff/<int:staff_id>', methods=['GET', 'POST'])
@login_required
def edit_staff(staff_id):
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT id, name FROM staff")
    staff_list = cursor.fetchall()  # Returns a list of tuples [(id1, name1), (id2, name2), ...]
    cursor.execute("SELECT id, name FROM department")
    department_list = cursor.fetchall()
    if request.method == 'POST':
        name = request.form['name']
        department = request.form['department']
        email = request.form['email']
        reportee = request.form['reportee']
        position = request.form['position']
        cursor.execute("UPDATE staff SET name = %s, department = %s, email = %s, reportee=%s, position=%s WHERE id = %s", (name, department,email,reportee,position, staff_id))
        mysql.connection.commit()
        flash('Staff updated successfully!', 'success')
        return redirect(url_for('admin'))
    cursor.execute("SELECT * FROM staff WHERE id = %s", [staff_id])
    staff = cursor.fetchone()
    return render_template('edit_staff.html', staff=staff,staff_list=staff_list, department_list=department_list)

@app.route('/delete_staff/<int:staff_id>')
@login_required
def delete_staff(staff_id):
    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM staff WHERE id = %s", [staff_id])
    mysql.connection.commit()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('admin'))

@app.route('/summary')
@login_required
def summary():
    period = request.args.get('period', 'daily')
    selected_date_str = request.args.get('date')

    # If `selected_date_str` is None or invalid, set it to today's date
    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date() if selected_date_str else datetime.now().date()
    except (ValueError, TypeError):
        selected_date = datetime.now().date()

    cursor = mysql.connection.cursor()

    # Determine the range of available dates for navigation
    cursor.execute("SELECT MIN(DATE(checkin_time)), MAX(DATE(checkin_time)) FROM attendance")
    min_date, max_date = cursor.fetchone()

    # If there's no attendance data, set min_date and max_date to None
    if not min_date or not max_date:
        min_date = max_date = None

    if period == 'daily':
        # Fetch attendance data for the selected date
        cursor.execute("""
            SELECT staff.name, 
                   MIN(attendance.checkin_time) AS first_checkin, 
                   MAX(attendance.checkout_time) AS last_checkout,
                   TIMEDIFF(MAX(attendance.checkout_time), MIN(attendance.checkin_time)) AS effective_hours
            FROM attendance 
            JOIN staff ON attendance.staff_id = staff.id
            WHERE DATE(attendance.checkin_time) = %s
            GROUP BY staff.id
        """, [selected_date])
        summary_data = cursor.fetchall()

        # Determine availability of previous and next dates
        previous_date = (selected_date - timedelta(days=1)) if min_date and selected_date > min_date else None
        next_date = (selected_date + timedelta(days=1)) if max_date and selected_date < max_date and selected_date < datetime.now().date() else None

        return render_template('summary.html', summary_data=summary_data, period='daily', selected_date=selected_date, previous_date=previous_date, next_date=next_date, min_date=min_date, max_date=max_date, timedelta=timedelta)

    elif period == 'weekly':
        # Fetch attendance data for the selected week
        week_start = selected_date - timedelta(days=selected_date.weekday())
        week_end = week_start + timedelta(days=6)

        cursor.execute("""
            SELECT staff.name, DATE(attendance.checkin_time) AS day, 
                   MIN(attendance.checkin_time) AS first_checkin, 
                   MAX(attendance.checkout_time) AS last_checkout,
                   TIMEDIFF(MAX(attendance.checkout_time), MIN(attendance.checkin_time)) AS effective_hours
            FROM attendance 
            JOIN staff ON attendance.staff_id = staff.id
            WHERE DATE(attendance.checkin_time) BETWEEN %s AND %s
            GROUP BY staff.id, day
        """, (week_start, week_end))
        weekly_data = cursor.fetchall()

        # Prepare weekly summary with attendance status for each day
        summary_data = {}
        for staff_name, day, first_checkin, last_checkout, effective_hours in weekly_data:
            if staff_name not in summary_data:
                summary_data[staff_name] = {week_start + timedelta(days=i): {'status': 'absent', 'first_checkin': None, 'last_checkout': None, 'effective_hours': None} for i in range(7)}
            summary_data[staff_name][day] = {'status': 'present', 'first_checkin': first_checkin, 'last_checkout': last_checkout, 'effective_hours': effective_hours}

        # Determine availability of previous and next weeks
        previous_week = (week_start - timedelta(weeks=1)) if min_date and week_start > min_date else None
        next_week = (week_start + timedelta(weeks=1)) if max_date and week_start + timedelta(weeks=1) <= datetime.now().date() else None

        return render_template('summary.html', summary_data=summary_data, period='weekly', week_start=week_start, week_end=week_end, previous_week=previous_week, next_week=next_week, min_date=min_date, max_date=max_date, timedelta=timedelta)

@app.route('/departments')
@login_required
def department():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM department")
    department_list = cursor.fetchall()
    return render_template('departments.html', department_list=department_list)

@app.route('/add_department', methods=['POST'])
@login_required
def add_department():
    if request.method == 'POST':
        name = request.form['department_name']
        if name:
            cursor = mysql.connection.cursor()
            cursor.execute("INSERT INTO department (name) VALUES (%s)", [name])
            mysql.connection.commit()
            flash('Department added successfully!', 'success')
        else:
            flash('Please fill in all fields.', 'danger')
        return redirect(url_for('department'))   

@app.route('/company_hierarchy')
@login_required
def company_hierarchy():
    cursor = mysql.connection.cursor()

    # Updated query to include position
    cursor.execute("""
        SELECT s.id, s.name, s.reportee, d.name AS department_name, s.position
        FROM staff s
        JOIN department d ON s.department = d.id
        ORDER BY d.name ASC, s.reportee ASC
    """)

    # Fetch all staff data
    staff_data = cursor.fetchall()

    # Create a dictionary to map staff by their id
    staff_dict = {
        staff[0]: {
            'id': staff[0],
            'name': staff[1],
            'reportee': staff[2],
            'department': staff[3],
            'position': staff[4],  # Include position here
            'subordinates': []
        }
        for staff in staff_data
    }

    # Build the hierarchy (tree structure)
    for staff in staff_data:
        staff_id, name, manager_id, department_name, position = staff
        if manager_id != 0:  # If the staff member has a manager
            staff_dict[manager_id]['subordinates'].append(staff_dict[staff_id])

    # Top-level managers (those with reportee = 0)
    top_managers = [staff_dict[staff[0]] for staff in staff_data if staff[2] == 0]

    def bfs_tree(manager):
        """ Build a tree using BFS to ensure layer-by-layer traversal. """
        from collections import deque
        queue = deque([(manager, 0)])  # (current_node, level)
        tree = []

        while queue:
            node, level = queue.popleft()

            # Add current node to the tree
            if len(tree) <= level:
                tree.append([])
            tree[level].append({
                'name': node['name'],
                'department': node['department'],
                'position': node['position']
            })

            # Add subordinates to the queue
            for sub in sorted(node['subordinates'], key=lambda x: x['id']):
                queue.append((sub, level + 1))
        return tree

    # Generate trees for all top managers
    trees = [bfs_tree(manager) for manager in top_managers]

    return render_template('hierarchy.html', trees=trees)

@app.route('/attendence')
@login_required
def home():
    cursor = mysql.connection.cursor()
    cursor.execute("""
    SELECT 
        s.id, 
        s.name, 
        d.name AS department, 
        CASE 
            WHEN (SELECT COUNT(*) FROM attendance a WHERE a.staff_id = s.id AND a.checkout_time IS NULL) > 0 
            THEN 'checked_in'
            ELSE 'checked_out'
        END AS attendance_status
    FROM staff s
    LEFT JOIN department d ON s.department = d.id
""")

    staff_list = cursor.fetchall()
    return render_template('attendence.html', staff_list=staff_list)

# Mark attendance
@app.route('/checkin/<int:staff_id>', methods=['POST'])
@login_required
def checkin(staff_id):
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO attendance (staff_id, checkin_time) VALUES (%s, NOW())", [staff_id])
    mysql.connection.commit()
    flash('Staff checked in successfully!', 'success')
    return redirect(url_for('home'))

@app.route('/checkout/<int:staff_id>', methods=['POST'])
@login_required
def checkout(staff_id):
    cursor = mysql.connection.cursor()
    cursor.execute("""
        UPDATE attendance 
        SET checkout_time = NOW() 
        WHERE staff_id = %s AND checkout_time IS NULL
        ORDER BY checkin_time DESC LIMIT 1
    """, [staff_id])
    mysql.connection.commit()
    flash('Staff checked out successfully!', 'success')
    return redirect(url_for('home'))

# Function to generate an invoice based on user input
def generate_invoice(data):
    # Load the template
    doc = Document("invoice.docx")

    # Update dynamic fields
    for para in doc.paragraphs:
        if "Grand Total:" in para.text:
            para.text = f"Grand Total: Rupees {data['grand_total_text']} Rs.{data['grand_total']}/-"

    # Update Table 1 (Header Details)
    table1 = doc.tables[0]  # Assuming Table 1 holds header information
    invoice_date = datetime.strptime(data["invoice_date"], "%Y-%m-%d").strftime("%B %d, %Y")
    table1.rows[1].cells[0].text = invoice_date
    run = table1.rows[1].cells[0].paragraphs[0].runs[0]
    run.font.size = Pt(16)

    table1.rows[1].cells[1].text = f"INVOICE#{data['invoice_number']}"
    run = table1.rows[1].cells[1].paragraphs[0].runs[0]
    run.font.size = Pt(16)

    # Update Table 2 (Due Date)
    table2 = doc.tables[1]  # Assuming Table 2 holds due date
    invoice_date_obj = datetime.strptime(data["invoice_date"], "%Y-%m-%d")
    due_date = (invoice_date_obj + timedelta(days=14)).strftime("%B %d, %Y")
    table2.rows[1].cells[3].text = due_date
    
    

    # Update Table 3 (Services Summary)
    table3 = doc.tables[2]
    new_row = table3.add_row()  # Add a new row for services
    new_row.cells[0].text = "1"
    new_row.cells[1].text = data["billable_hours"]
    new_row.cells[2].text = f"Rs. {data['amount_per_hour']}"
    new_row.cells[3].text = data["start_date"]
    new_row.cells[4].text = data["end_date"]
    new_row.cells[5].text = f"Rs. {data['subtotal']}"

    # Update Table 5 (Totals Table)
    table5 = doc.tables[4]  # Assuming Table 5 holds totals
    table5.rows[0].cells[1].text = f"Rs. {data['subtotal']}"
    table5.rows[1].cells[1].text = f"Rs. {data['gst']}"
    table5.rows[2].cells[1].text = f"Rs. {data['grand_total']}"

    # Save the modified document in memory
    output_stream = BytesIO()
    doc.save(output_stream)
    output_stream.seek(0)

    return output_stream

@app.route('/reciept')
@login_required
def reciept():
    return render_template('invoice_form.html')

@app.route('/generate', methods=['POST'])
@login_required
def pdf_download():
    file_name = generate()
    try:
        pythoncom.CoInitialize()
        docx2pdf.convert(file_name)  # DOCX -> PDF (in-place or specify output path)
    finally:
        pythoncom.CoUninitialize()
    pdf_file_name = file_name.replace("docx", "pdf")
    return send_file(pdf_file_name, as_attachment=True)
def generate():
    # 1. Gather form data
    form_data = request.form
    invoice_data = {
        "invoice_date": form_data.get("invoice_date"),
        "invoice_number": form_data.get("invoice_number"),
        "billable_hours": form_data.get("billable_hours"),
        "amount_per_hour": form_data.get("amount_per_hour"),
        "start_date": form_data.get("start_date"),
        "end_date": form_data.get("end_date"),
        "subtotal": form_data.get("subtotal"),
        "gst": form_data.get("gst"),
        "grand_total": form_data.get("grand_total"),
        "grand_total_text": form_data.get("grand_total_text"),
        "total_amount": form_data.get("total_amount"),
    }
    # 2. Generate the invoice (returns a BytesIO in-memory file)
    invoice_file = generate_invoice(invoice_data)  # invoice_file is BytesIO
    
    # 3. Choose the output filename
    file_name = f"invoices/invoice_{invoice_data['invoice_number']}.docx"
    # 4. Write the BytesIO object to an actual file on disk
    with open(file_name, "wb") as f:
        f.write(invoice_file.getvalue())
    # 5. Return the name of the file (or handle as needed)
    return file_name

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        role = request.form['role']
        password = request.form['password']
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT id, username, role, password FROM staff WHERE username = %s AND role = %s", (username, role))
        user = cursor.fetchone()
        # if user and check_password_hash(user[3], password):  # Ensure password hashing
        if user and user[3]== password:  # Ensure password hashing
            user_obj = User(id=user[0], username=user[1], role=user[2])
            login_user(user_obj)
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    cursor = mysql.connection.cursor()

    # Fetch current user details
    cursor.execute("""
        SELECT s.id, s.name, s.username, s.email, s.phone, s.position, d.name AS department, 
               r.name AS reportee, s.profile_picture
        FROM staff s
        LEFT JOIN department d ON s.department = d.id
        LEFT JOIN staff r ON s.reportee = r.id
        WHERE s.id = %s
    """, [current_user.id])
    user = cursor.fetchone()

    if not user:
        flash('User not found!', 'danger')
        return redirect(url_for('login'))

    # Map user data
    user_data = {
        'id': user[0],
        'name': user[1],
        'username': user[2],
        'email': user[3],
        'phone': user[4],
        'position': user[5],
        'department': user[6],
        'reportee': user[7],
        'profile_picture': user[8]
    }

    if request.method == 'POST':
        # Only update editable fields
        name = request.form['name']
        phone = request.form['phone']
        profile_picture = None

        # Handle profile picture upload
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename != '':
                # Validate file type
                allowed_extensions = {'png', 'jpg', 'jpeg'}
                file_extension = file.filename.rsplit('.', 1)[-1].lower()
                if file_extension not in allowed_extensions:
                    flash('Invalid file type! Only PNG, JPG, and JPEG are allowed.', 'danger')
                    return redirect(url_for('profile'))

                # Generate a unique filename
                filename = f"{current_user.id}_{secure_filename(file.filename)}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                # Save the file
                file.save(filepath)

                # Save the relative path (using forward slashes)
                profile_picture = f"uploads/{filename}"

        # Update the database
        if profile_picture:
            cursor.execute("""
                UPDATE staff SET name = %s, phone = %s, profile_picture = %s WHERE id = %s
            """, (name, phone, profile_picture, current_user.id))
        else:
            cursor.execute("""
                UPDATE staff SET name = %s, phone = %s WHERE id = %s
            """, (name, phone, current_user.id))

        mysql.connection.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))

    return render_template('profile.html', user=user_data)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
