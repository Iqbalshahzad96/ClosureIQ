"""Synthetic canonical records preserving existing MCP/workflow test scenarios."""
from decimal import Decimal
from app.database.models import Account, BankAccount, BankTransaction, JournalEntry, JournalLine


def financial_record(session, *, id, source, account_code, amount, transaction_date=None,
                     description=None, reference=None, is_reconciled=False):
    account=session.query(Account).filter_by(account_code=account_code,organization_id='default_org').first()
    if account is None:
        account=Account(account_code=account_code,account_name=account_code,normalized_name=account_code,
                        account_type='ASSET',currency_code='KES')
        session.add(account); session.flush()
    value=Decimal(str(amount))
    if source=='GL':
        entry=JournalEntry(id='entry_'+id,entry_date=transaction_date,reference=reference,
                           description=description,currency_code='KES')
        session.add(entry); session.flush()
        return JournalLine(id=id,journal_entry_id=entry.id,account_id=account.id,
            debit_amount=max(value,Decimal(0)),credit_amount=max(-value,Decimal(0)),
            description=description,is_reconciled=is_reconciled)
    bank=session.query(BankAccount).filter_by(linked_gl_account_id=account.id).first()
    if bank is None:
        bank=BankAccount(linked_gl_account_id=account.id,bank_name='Demo',
                          account_number_masked='***',account_name=account_code,currency_code='KES')
        session.add(bank); session.flush()
    return BankTransaction(id=id,bank_account_id=bank.id,booking_date=transaction_date,amount=value,
                           bank_reference=reference,description=description,is_reconciled=is_reconciled)
