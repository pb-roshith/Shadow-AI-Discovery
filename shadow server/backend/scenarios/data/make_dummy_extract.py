"""Deterministic fictional extract, exactly 14 accounts and 2,400,000 bytes."""
import csv
import io
import random
from pathlib import Path

FILLER = 'fictional training record only; harmless padding for demo purposes. '
DISCLAIMER = '# FICTIONAL DEMO DATA – NOT REAL CUSTOMERS\n'
TARGET_BYTES = 2_400_000


def generate(path=None):
    path = Path(path) if path else Path(__file__).with_name('dummy_customer_extract.csv')
    rng = random.Random(42)
    output = io.StringIO(newline='')
    output.write(DISCLAIMER)
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow(['customer_name', 'account_no', 'city', 'product', 'notes'])
    rows = [[f'Fictional Customer {i + 1:02}', f'ACC-{123456 + i:010}',
             rng.choice(['Demo City', 'Example Town']), 'Demo Loan', ''] for i in range(14)]
    for row in rows:
        writer.writerow(row)
    remaining = TARGET_BYTES - len(output.getvalue().encode('utf-8'))
    output.seek(0)
    output.truncate()
    output.write(DISCLAIMER)
    writer.writerow(['customer_name', 'account_no', 'city', 'product', 'notes'])
    for i, row in enumerate(rows):
        size = remaining // 14 + (i < remaining % 14)
        row[-1] = (FILLER * (size // len(FILLER) + 1))[:size]
        writer.writerow(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output.getvalue().encode('utf-8'))
    return path


if __name__ == '__main__':
    print(f'Created fictional demo extract: {generate()}')
