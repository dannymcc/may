"""Loan payments work through the existing expense workflows."""
import json
import re

from app.models import Expense, RecurringExpense


def test_loan_payment_save_edit_and_chart(auth_client, sample_vehicle):
    form = auth_client.get('/expenses/new')
    assert b'value="loan_payment"' in form.data
    assert b'Loan Payment' in form.data
    response = auth_client.post('/expenses/new', data={
        'vehicle_id': str(sample_vehicle.id), 'date': '2026-10-01',
        'category': 'loan_payment', 'description': 'Monthly loan', 'cost': '425.50',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Loan Payment' in response.data
    expense = Expense.query.filter_by(description='Monthly loan').one()
    assert expense.category == 'loan_payment'
    assert expense.cost == 425.50
    response = auth_client.post(f'/expenses/{expense.id}/edit', data={
        'date': '2026-10-01', 'category': 'loan_payment',
        'description': 'Monthly loan', 'cost': '430.50',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert expense.category == 'loan_payment'
    assert expense.cost == 430.50
    page = auth_client.get(f'/vehicles/{sample_vehicle.id}')
    chart = re.search(r'const categoryData = (\{.*?\});', page.text, re.DOTALL)
    assert chart
    assert json.loads(chart.group(1))['Loan Payment'] == 430.50


def test_recurring_loan_payment_generates_expense(auth_client, sample_vehicle):
    form = auth_client.get('/recurring/new')
    assert b'value="loan_payment"' in form.data
    response = auth_client.post('/recurring/new', data={
        'vehicle_id': str(sample_vehicle.id), 'name': 'Monthly loan',
        'category': 'loan_payment', 'frequency': 'monthly',
        'amount': '425.50', 'start_date': '2026-10-01',
    }, follow_redirects=True)
    assert response.status_code == 200
    recurring = RecurringExpense.query.filter_by(name='Monthly loan').one()
    assert recurring.category == 'loan_payment'
    response = auth_client.post(f'/recurring/{recurring.id}/generate', follow_redirects=True)
    assert response.status_code == 200
    expense = Expense.query.filter_by(vehicle_id=sample_vehicle.id).one()
    assert expense.category == 'loan_payment'
    assert expense.cost == 425.50


def test_api_accepts_loan_payment(client, api_headers, sample_vehicle):
    response = client.post(f'/api/v1/vehicles/{sample_vehicle.id}/expenses',
        headers=api_headers, json={
            'date': '2026-10-01', 'category': 'loan_payment',
            'description': 'API loan payment', 'cost': 425.50,
        })
    assert response.status_code == 201
    expense = Expense.query.filter_by(description='API loan payment').one()
    assert expense.category == 'loan_payment'
    assert expense.cost == 425.50
