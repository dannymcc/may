from datetime import date, timedelta

from app import db
from app.models import Expense, RecurringExpense
from app.services.recurring_processor import process_due_recurring_expenses


def test_biweekly_form_save_and_generate(auth_client, sample_vehicle):
    form = auth_client.get('/recurring/new')
    assert b'Biweekly (every 2 weeks)' in form.data
    response = auth_client.post('/recurring/new', data={
        'vehicle_id': sample_vehicle.id, 'name': 'Biweekly loan',
        'category': 'loan_payment', 'frequency': 'biweekly',
        'amount': '200', 'start_date': '2026-12-25',
    }, follow_redirects=True)
    assert response.status_code == 200
    recurring = RecurringExpense.query.filter_by(name='Biweekly loan').one()
    assert recurring.frequency == 'biweekly'
    form = auth_client.get(f'/recurring/{recurring.id}/edit')
    assert b'value="biweekly" selected' in form.data
    response = auth_client.post(f'/recurring/{recurring.id}/generate')
    assert response.status_code == 302
    expense = Expense.query.filter_by(vehicle_id=sample_vehicle.id).one()
    assert expense.date == date(2026, 12, 25)
    assert expense.category == 'loan_payment'
    assert recurring.next_due == date(2027, 1, 8)


def test_biweekly_catchup_does_not_duplicate(app, test_user, sample_vehicle):
    today = date.today()
    start = today - timedelta(days=28)
    recurring = RecurringExpense(
        user_id=test_user.id, vehicle_id=sample_vehicle.id,
        name='Biweekly loan', category='loan_payment', amount=200,
        frequency='biweekly', start_date=start, next_due=start,
        auto_create=True, is_active=True,
    )
    db.session.add(recurring)
    db.session.commit()
    assert process_due_recurring_expenses()['generated'] == 3
    expenses = Expense.query.filter_by(vehicle_id=sample_vehicle.id).order_by(Expense.date).all()
    assert [expense.date for expense in expenses] == [start, start + timedelta(days=14), today]
    assert recurring.next_due == today + timedelta(days=14)
    assert process_due_recurring_expenses()['generated'] == 0
