from flask import Flask,render_template
app=Flask('__name__')
@app.route('/')
def home():
    return render_template('index.html')
@app.route('/register')
def registerpage():
    return render_template('registration.html')
@app.route('/login')
def login():
    return render_template('login.html')
@app.route('/analyze')
def analyze():
    return render_template('dashboard.html')
if __name__=='__main__':
    app.run(debug=True,host='0.0.0.0')