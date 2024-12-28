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




app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Database configuration
with open('db.yaml', 'r') as db_file:
    db_config = yaml.safe_load(db_file)

app.config['MYSQL_HOST'] = db_config['mysql_host']
app.config['MYSQL_USER'] = db_config['mysql_user']
app.config['MYSQL_PASSWORD'] = db_config['mysql_password']
app.config['MYSQL_DB'] = db_config['mysql_db']

mysql = MySQL(app)

# Admin console for managing staff
@app.route('/')
def index():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM staff")
    total_staff = cursor.fetchone()[0]  # Get the total number of staff
    cursor.execute("SELECT COUNT(DISTINCT staff_id) FROM attendance WHERE DATE(checkin_time) = CURDATE()")
    checked_in_today = cursor.fetchone()[0] 
    cursor.execute("SELECT COUNT(id) FROM department")
    department_count = cursor.fetchone()[0]
    return render_template('index.html', total_staff=total_staff, present_today=checked_in_today, department_count=department_count)
   
@app.route('/admin')
def admin():
    cursor = mysql.connection.cursor()
    cursor.execute("""
    SELECT 
        s.id, 
        s.name, 
        d.name AS department FROM staff s
    LEFT JOIN department d ON s.department = d.id
""")
    staff_list = cursor.fetchall()
    return render_template('admin.html', staff_list=staff_list)

@app.route('/onboard', methods=['GET'])
def onboard():
    # Fetch all existing staff for the dropdown
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT id, name FROM staff")
    staff_list = cursor.fetchall()  # Returns a list of tuples [(id1, name1), (id2, name2), ...]
    cursor.execute("SELECT id, name FROM department")
    department_list = cursor.fetchall()
    return render_template('onboard.html', staff_list=staff_list, department_list=department_list)

@app.route('/add_staff', methods=['POST'])
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
def delete_staff(staff_id):
    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM staff WHERE id = %s", [staff_id])
    mysql.connection.commit()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('admin'))

@app.route('/summary')
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
def department():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM department")
    department_list = cursor.fetchall()
    return render_template('departments.html', department_list=department_list)

@app.route('/add_department', methods=['POST'])
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
def company_hierarchy():
    cursor = mysql.connection.cursor()

    # Query to fetch all staff members with department and their direct managers
    cursor.execute("""
        SELECT s.id, s.name, s.reportee, d.name AS department_name
        FROM staff s
        JOIN department d ON s.department = d.id
    """)

    # Fetch all staff data
    staff_data = cursor.fetchall()

    # Create a dictionary to map staff by their id
    staff_dict = {staff[0]: {'id': staff[0], 'name': staff[1], 'reportee': staff[2], 'department': staff[3], 'subordinates': []} for staff in staff_data}

    # Build the hierarchy (tree structure)
    for staff in staff_data:
        staff_id, name, manager_id, department_name = staff
        if manager_id != 0:  # If the staff member has a manager
            staff_dict[manager_id]['subordinates'].append(staff_dict[staff_id])

    # Top-level managers (those with reportee = 0)
    top_managers = [staff_dict[staff[0]] for staff in staff_data if staff[2] == 0]

    # Limit the recursion level to avoid exceeding max recursion depth
    def build_tree(manager, level=1):
        """ Recursively build a tree but keep track of recursion depth """
        tree = {
            'name': manager['name'],
            'department': manager['department'],
            'subordinates': []
        }

        if level < 11:  # Set maximum depth
            for sub in manager['subordinates']:
                tree['subordinates'].append(build_tree(sub, level + 1))
        return tree

    # Convert staff data to a tree with limited depth
    tree_data = [build_tree(manager) for manager in top_managers]

    return render_template('hierarchy.html', tree_data=tree_data)

@app.route('/attendence')
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
def checkin(staff_id):
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO attendance (staff_id, checkin_time) VALUES (%s, NOW())", [staff_id])
    mysql.connection.commit()
    flash('Staff checked in successfully!', 'success')
    return redirect(url_for('home'))

@app.route('/checkout/<int:staff_id>', methods=['POST'])
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
    due_date = (invoice_date_obj + timedelta(days=7)).strftime("%B %d, %Y")
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
def reciept():
    return render_template('invoice_form.html')


@app.route('/generate', methods=['POST'])
def generate_pdf():
    # 1. Create or load your .docx (example uses python-docx to create)
    doc = Document()
    doc.add_paragraph("Hello from a docx file!")
    docx_io = io.BytesIO()
    doc.save(docx_io)
    docx_io.seek(0)

    # 2. Write the in-memory DOCX to a temporary file
    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = os.path.join(tmpdir, "file.docx")
        pdf_path = os.path.join(tmpdir, "file.pdf")

        # Write .docx to disk
        with open(docx_path, "wb") as f:
            f.write(docx_io.getvalue())

        # 3. Run unoconv to convert DOCX -> PDF
        #    unoconv -f pdf -o file.pdf file.docx
        subprocess.run([
            "unoconv",
            "-f", "pdf",
            "-o", pdf_path,
            docx_path
        ], check=True)

        # 4. Send the PDF back to the user
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name="converted.pdf",
            mimetype="application/pdf",
        )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
