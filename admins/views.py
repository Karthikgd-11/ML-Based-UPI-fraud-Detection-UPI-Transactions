import os
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from django.contrib import messages
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_protect
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import VotingClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC
from xgboost import XGBClassifier
from .forms import UserRegistrationForm
from .models import UserRegistrationModel, UPITransaction

BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_PATH = BASE_DIR / 'media'
DATASET_PATH = MEDIA_PATH / 'upi_fraud_enhanced_dataset.csv'


def _load_dataset():
    return pd.read_csv(DATASET_PATH)


def _load_models():
    try:
        return (
            joblib.load(MEDIA_PATH / 'voting_model.pkl'),
            joblib.load(MEDIA_PATH / 'scaler.pkl'),
            joblib.load(MEDIA_PATH / 'label_encoders.pkl'),
            joblib.load(MEDIA_PATH / 'feature_columns.pkl'),
        )
    except Exception:
        return None, None, {}, []


def training(request):
    MEDIA_PATH.mkdir(exist_ok=True)
    df = _load_dataset()
    df.drop(columns=['transaction_id', 'timestamp', 'user_id', 'merchant_id', 'device_id'], inplace=True, errors='ignore')
    categorical_cols = df.select_dtypes(include=['object']).columns
    label_encoders = {}
    for col in categorical_cols:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col].astype(str))
        label_encoders[col] = le

    feature_columns = df.drop('is_fraud', axis=1).columns.tolist()
    X, y = df[feature_columns], df['is_fraud']
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.3, random_state=42, stratify=y
    )
    models = {
        'LogisticRegression': LogisticRegression(max_iter=1000),
        'DecisionTree': DecisionTreeClassifier(random_state=42),
        'XGBoost': XGBClassifier(eval_metric='logloss', random_state=42),
        'SVM': SVC(probability=True, random_state=42),
        'KNN': KNeighborsClassifier(),
        'NaiveBayes': GaussianNB(),
    }
    results = {}
    for name, model in models.items():
        model.fit(X_train, y_train)
        joblib.dump(model, MEDIA_PATH / f'{name}.pkl')
        y_pred = model.predict(X_test)
        results[name] = {
            'Accuracy': round(accuracy_score(y_test, y_pred), 4),
            'Precision': round(precision_score(y_test, y_pred, zero_division=0), 4),
            'Recall': round(recall_score(y_test, y_pred, zero_division=0), 4),
            'F1 Score': round(f1_score(y_test, y_pred, zero_division=0), 4),
        }
    voting_clf = VotingClassifier(estimators=list(models.items()), voting='soft')
    voting_clf.fit(X_train, y_train)
    joblib.dump(voting_clf, MEDIA_PATH / 'voting_model.pkl')
    y_pred = voting_clf.predict(X_test)
    results['VotingClassifier'] = {
        'Accuracy': round(accuracy_score(y_test, y_pred), 4),
        'Precision': round(precision_score(y_test, y_pred, zero_division=0), 4),
        'Recall': round(recall_score(y_test, y_pred, zero_division=0), 4),
        'F1 Score': round(f1_score(y_test, y_pred, zero_division=0), 4),
    }
    joblib.dump(scaler, MEDIA_PATH / 'scaler.pkl')
    joblib.dump(label_encoders, MEDIA_PATH / 'label_encoders.pkl')
    joblib.dump(feature_columns, MEDIA_PATH / 'feature_columns.pkl')
    return render(request, 'users/training.html', {'results': results})


def UserRegisterActions(request):
    if request.method == 'POST':
        post_data = request.POST.copy()
        post_data['status'] = 'waiting'
        form = UserRegistrationForm(post_data)
        if form.is_valid():
            user = form.save(commit=False)
            user.status = 'waiting'
            user.save()
            messages.success(request, f'Account created for {user.name}. Please wait for admin activation before logging in.')
            return redirect('UserLogin')
        else:
            messages.error(request, 'Registration failed. Please correct the highlighted fields. Login ID, mobile number, or email may already exist.')
    else:
        form = UserRegistrationForm()
    return render(request, 'UserRegistrations.html', {'form': form})


@csrf_protect
def UserLoginCheck(request):
    if request.method == 'POST':
        loginid = request.POST.get('loginid', '').strip()
        pswd = request.POST.get('pswd', '')
        try:
            check = UserRegistrationModel.objects.get(loginid=loginid, password=pswd)
            if check.status == 'activated':
                request.session['id'] = check.id
                request.session['loggeduser'] = check.name
                request.session['loginid'] = loginid
                request.session['email'] = check.email
                return render(request, 'users/UserHomePage.html', _dashboard_context())
            messages.warning(request, 'Your account is waiting for admin activation.')
        except UserRegistrationModel.DoesNotExist:
            messages.error(request, 'Invalid Login ID or password.')
    return render(request, 'UserLogin.html')


def _get_logged_user(request):
    user_id = request.session.get('id')
    if not user_id:
        return None
    try:
        return UserRegistrationModel.objects.get(id=user_id)
    except UserRegistrationModel.DoesNotExist:
        return None


def logout_user(request):
    request.session.flush()
    return redirect('index')


def send_money(request):
    user = _get_logged_user(request)
    if not user:
        return redirect('UserLogin')
    df = _load_dataset()
    choices = {col: sorted(df[col].dropna().astype(str).unique().tolist()) for col in ['transaction_type','authentication_method']}
    context = {'choices': choices, 'input_data': {}, 'result': None}
    if request.method == 'POST':
        try:
            receiver = request.POST.get('receiver','').strip()
            amount = float(request.POST['amount'])
            state = request.POST['state'].strip()
            district = request.POST['district'].strip()
            subdistrict = request.POST['subdistrict'].strip()
            location = subdistrict
            transaction_type = request.POST['transaction_type']
            authentication_method = request.POST['authentication_method']
            frequency = int(request.POST['transaction_frequency'])
            success_rate = float(request.POST['historical_success_rate'])
            pin = request.POST.get('pin','').strip()
            if not receiver or not state or not district or not subdistrict or amount <= 0 or frequency < 0 or not 0 <= success_rate <= 1 or not (pin.isdigit() and len(pin)==4):
                raise ValueError
        except (KeyError, ValueError):
            context['message'] = 'Enter valid details. Demo UPI PIN must contain exactly 4 digits.'
            context['input_data'] = request.POST
            return render(request, 'users/send_money.html', context)

        voting_model, scaler, encoders, feature_columns = _load_models()
        if voting_model is None:
            context['message'] = 'ML model files are missing. Run Model Training first.'
            return render(request, 'users/send_money.html', context)
        row = pd.DataFrame([{'amount': amount, 'location': location, 'transaction_type': transaction_type, 'authentication_method': authentication_method, 'transaction_frequency': frequency, 'historical_success_rate': success_rate}])
        for col in encoders:
            if col in row.columns:
                row[col] = row[col].apply(lambda x: safe_label_encode(encoders, col, x))
        for col in feature_columns:
            if col not in row.columns:
                row[col] = 0
        row = row[feature_columns]
        scaled = scaler.transform(row)
        pred = int(voting_model.predict(scaled)[0])
        probability = float(voting_model.predict_proba(scaled)[0][1]) * 100
        if probability >= 70 or pred == 1:
            risk, status = 'High', 'Blocked'
        elif probability >= 30:
            risk, status = 'Medium', 'Verification Required'
        else:
            risk, status = 'Low', 'Success'
        if status != 'Blocked':
            UPITransaction.objects.create(user=user, receiver=receiver, amount=amount, location=location, state=state, district=district, subdistrict=subdistrict, transaction_type=transaction_type, authentication_method=authentication_method, transaction_frequency=frequency, historical_success_rate=success_rate, fraud_probability=round(probability,2), risk_level=risk, status=status)
        context.update({'result': {'receiver': receiver, 'amount': f'{amount:,.2f}', 'state': state, 'district': district, 'subdistrict': subdistrict, 'probability': round(probability,2), 'risk': risk, 'status': status}})
    return render(request, 'users/send_money.html', context)


def _dashboard_context():
    df = _load_dataset()
    total = len(df)
    fraud = int(df['is_fraud'].sum())
    genuine = total - fraud
    alerts = int(((df['is_fraud'] == 1) & ((df['amount'] >= df['amount'].quantile(.75)) | (df['transaction_frequency'] >= df['transaction_frequency'].quantile(.90)))).sum())
    dates = pd.to_datetime(df['timestamp'], errors='coerce').dt.date
    daily = df.assign(day=dates).groupby(['day', 'is_fraud']).size().unstack(fill_value=0).tail(7)
    labels = [d.strftime('%d %b') for d in daily.index]
    genuine_series = [int(daily.loc[d].get(0, 0)) for d in daily.index]
    fraud_series = [int(daily.loc[d].get(1, 0)) for d in daily.index]
    return {
        'total_transactions': total,
        'genuine_transactions': genuine,
        'fraudulent_transactions': fraud,
        'alerts_generated': alerts,
        'genuine_pct': round(genuine / total * 100, 1) if total else 0,
        'fraud_pct': round(fraud / total * 100, 1) if total else 0,
        'chart_labels': labels,
        'genuine_series': genuine_series,
        'fraud_series': fraud_series,
    }


def UserHome(request):
    return render(request, 'users/UserHomePage.html', _dashboard_context())


def transactions(request):
    user = _get_logged_user(request)
    if user and UPITransaction.objects.filter(user=user).exists():
        rows = []
        qs = UPITransaction.objects.filter(user=user)[:100]
        for r in qs:
            rows.append({'id': f'TXN{r.id:06d}', 'date': r.created_at.strftime('%d-%m-%Y %H:%M'), 'amount': f'{float(r.amount):,.2f}', 'location': ' / '.join([x for x in [r.state, r.district, r.subdistrict] if x]) or r.location, 'type': r.transaction_type, 'auth': r.authentication_method, 'status': r.status, 'risk': r.risk_level, 'receiver': r.receiver})
        return render(request, 'users/transactions.html', {'transactions': rows, 'total_count': UPITransaction.objects.filter(user=user).count(), 'live_transactions': True})
    df = _load_dataset().copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.strftime('%d-%m-%Y %H:%M')
    rows = []
    for _, r in df.head(100).iterrows():
        rows.append({
            'id': str(r['transaction_id'])[:12].upper(),
            'date': r['timestamp'], 'amount': f"{float(r['amount']):,.2f}",
            'location': r['location'], 'type': r['transaction_type'],
            'auth': r['authentication_method'], 'status': 'Fraud' if int(r['is_fraud']) else 'Success', 'risk': 'High' if int(r['is_fraud']) else 'Low', 'receiver': 'Dataset transaction'
        })
    return render(request, 'users/transactions.html', {'transactions': rows, 'total_count': len(df)})


def alerts(request):
    df = _load_dataset().copy()
    df = df[df['is_fraud'] == 1].sort_values('amount', ascending=False).head(100)
    rows = []
    for i, (_, r) in enumerate(df.iterrows(), 1):
        risk = 'High' if float(r['amount']) >= df['amount'].median() else 'Medium'
        rows.append({'id': f'ALRT{i:04d}', 'txn': str(r['transaction_id'])[:12].upper(), 'type': 'High Amount' if risk == 'High' else 'Suspicious Transaction', 'risk': risk, 'time': pd.to_datetime(r['timestamp']).strftime('%d-%m-%Y %H:%M'), 'status': 'Open'})
    return render(request, 'users/alerts.html', {'alerts': rows, 'total_alerts': len(df)})


def viewdataset(request):
    df = _load_dataset()
    preview = df.head(200).to_html(classes='ui-table', index=False, border=0)
    return render(request, 'users/viewdataset.html', {'data': preview, 'rows': len(df), 'columns': len(df.columns)})


def safe_label_encode(encoders, column, value):
    encoder = encoders.get(column)
    if encoder is None:
        return 0
    try:
        return int(encoder.transform([str(value)])[0])
    except ValueError:
        return 0


@csrf_protect
def prediction(request):
    voting_model, scaler, label_encoders, feature_columns = _load_models()
    choices = {}
    if DATASET_PATH.exists():
        df = _load_dataset()
        for col in ['location', 'transaction_type', 'authentication_method']:
            choices[col] = sorted(df[col].dropna().astype(str).unique().tolist())
    context = {'input_data': {}, 'choices': choices}
    if voting_model is None or scaler is None or not feature_columns:
        context['message'] = 'Model files are not available. Open Model Training first.'
        return render(request, 'users/prediction.html', context)
    if request.method == 'POST':
        try:
            input_data = {
                'amount': float(request.POST['amount']),
                'location': request.POST['location'],
                'transaction_type': request.POST['transaction_type'],
                'authentication_method': request.POST['authentication_method'],
                'transaction_frequency': int(request.POST['transaction_frequency']),
                'historical_success_rate': float(request.POST['historical_success_rate']),
            }
            if input_data['amount'] <= 0 or input_data['transaction_frequency'] < 0 or not 0 <= input_data['historical_success_rate'] <= 1:
                raise ValueError
        except (KeyError, ValueError):
            context['message'] = 'Please enter valid values. Success rate must be between 0 and 1.'
            context['input_data'] = request.POST
            return render(request, 'users/prediction.html', context)

        input_df = pd.DataFrame([input_data])
        for col in label_encoders:
            if col in input_df.columns:
                input_df[col] = input_df[col].apply(lambda x: safe_label_encode(label_encoders, col, x))
        for col in feature_columns:
            if col not in input_df.columns:
                input_df[col] = 0
        input_df = input_df[feature_columns]
        input_scaled = scaler.transform(input_df)
        prediction_val = int(voting_model.predict(input_scaled)[0])
        probability = float(voting_model.predict_proba(input_scaled)[0][1])
        context.update({
            'prediction': 'FRAUD' if prediction_val == 1 else 'GENUINE',
            'fraud_probability': round(probability * 100, 2),
            'input_data': input_data,
        })
    return render(request, 'users/prediction.html', context)
