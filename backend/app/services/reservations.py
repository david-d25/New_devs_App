from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List
import logging
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# check_in_date is TIMESTAMPTZ, but "a month" is local wall-clock time for the
# property, not UTC. AT TIME ZONE p.timezone converts each booking into the
# property's own frame, so March in Paris is March in Paris - not March in UTC.
_MONTHLY_REVENUE_SQL = text("""
    SELECT COALESCE(SUM(r.total_amount), 0) AS total
    FROM reservations r
    JOIN properties p
      ON p.id = r.property_id AND p.tenant_id = r.tenant_id
    WHERE r.property_id = :property_id
      AND r.tenant_id = :tenant_id
      AND (r.check_in_date AT TIME ZONE p.timezone) >= :start_date
      AND (r.check_in_date AT TIME ZONE p.timezone) <  :end_date
""")


async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int, year: int) -> Decimal:
    """
    Calculates revenue for a specific month, in the property's own timezone.
    """
    from app.core.database_pool import db_pool

    # Naive local-time boundaries; the SQL puts bookings into the same frame.
    start_date = datetime(year, month, 1)
    if month < 12:
        end_date = datetime(year, month + 1, 1)
    else:
        end_date = datetime(year + 1, 1, 1)

    try:
        async with db_pool.get_session() as session:
            result = await session.execute(_MONTHLY_REVENUE_SQL, {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            })
            total = result.scalar_one()
    except (SQLAlchemyError, OSError, TimeoutError, RuntimeError) as e:
        logger.exception(
            "Monthly revenue query failed: property=%s tenant=%s %s-%02d",
            property_id, tenant_id, year, month,
        )
        raise HTTPException(
            status_code=503,
            detail="Revenue data is temporarily unavailable",
            headers={"Retry-After": "30"},
        ) from e

    return Decimal(str(total))

async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.
    """
    try:
        # Don't create a new pool every time, use a singleton
        from app.core.database_pool import db_pool

        async with db_pool.get_session() as session:
            if db_pool.session_factory:
                async with db_pool.get_session() as session:
                    # Use SQLAlchemy text for raw SQL
                    from sqlalchemy import text

                    query = text("""
                        SELECT
                            property_id,
                            SUM(total_amount) as total_revenue,
                            COUNT(*) as reservation_count
                        FROM reservations
                        WHERE property_id = :property_id AND tenant_id = :tenant_id
                        GROUP BY property_id
                    """)

                    result = await session.execute(query, {
                        "property_id": property_id,
                        "tenant_id": tenant_id
                    })
                    row = result.fetchone()

                    if row:
                        total_revenue = Decimal(str(row.total_revenue))
                        return {
                            "property_id": property_id,
                            "tenant_id": tenant_id,
                            "total": str(total_revenue),
                            "currency": "USD",
                            "count": row.reservation_count
                        }
                    else:
                        # No reservations found for this property
                        return {
                            "property_id": property_id,
                            "tenant_id": tenant_id,
                            "total": "0.00",
                            "currency": "USD",
                            "count": 0
                        }
            else:
                raise Exception("Database pool not available")
            
    except Exception as e:
        print(f"Database error for {property_id} (tenant: {tenant_id}): {e}")

        # Passing wrong (mock) values in prod when something is wrong with the database, should return 503 instead
        raise HTTPException(
            status_code=503,
            detail="Revenue data is temporarily unavailable",
            headers={"Retry-After": "30"},
        ) from e

        # This is what was here before (just for the record):
        # Create property-specific mock data for testing when DB is unavailable
        # This ensures each property shows different figures

#         mock_data = {
#             'prop-001': {'total': '1000.00', 'count': 3},
#             'prop-002': {'total': '4975.50', 'count': 4},
#             'prop-003': {'total': '6100.50', 'count': 2},
#             'prop-004': {'total': '1776.50', 'count': 4},
#             'prop-005': {'total': '3256.00', 'count': 3}
#         }
#
#         mock_property_data = mock_data.get(property_id, {'total': '0.00', 'count': 0})
#
#         return {
#             "property_id": property_id,
#             "tenant_id": tenant_id,
#             "total": mock_property_data['total'],
#             "currency": "USD",
#             "count": mock_property_data['count']
#         }
