"""Tests for init_job_node (workflow) with site_of_record_id."""
from unittest.mock import MagicMock, patch

import pytest

from winerank.crawler.workflow import init_job_node
from winerank.common.models import Job, JobStatus, SiteOfRecord


def test_init_job_node_requires_site_of_record_id_for_new_job():
    """When starting a new job (no job_id), site_of_record_id must be in state."""
    state = {
        "michelin_level": "3",
        "force_recrawl": False,
    }
    with pytest.raises(ValueError) as exc_info:
        init_job_node(state)
    assert "site_of_record_id" in str(exc_info.value)


def test_init_job_node_uses_site_of_record_id_from_state():
    """init_job_node uses site_of_record_id from state to load site and create job."""
    mock_site = MagicMock()
    mock_site.id = 10
    mock_session = MagicMock()
    mock_session.query.return_value.filter_by.return_value.first.side_effect = [
        mock_site,  # SiteOfRecord lookup by id
    ]
    mock_session.add = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.flush = MagicMock()

    with patch("winerank.crawler.workflow.get_session") as mock_get_session:
        mock_get_session.return_value.__enter__.return_value = mock_session
        mock_get_session.return_value.__exit__.return_value = None

        state = {
            "site_of_record_id": 10,
            "michelin_level": "2",
            "force_recrawl": False,
            "restaurant_filter": None,
        }
        result = init_job_node(state)

    assert "job_id" in result
    assert result["site_of_record_id"] == 10
    assert result["michelin_level"] == "2"
    mock_session.add.assert_called()
    call_args = mock_session.add.call_args[0][0]
    assert isinstance(call_args, Job)
    assert call_args.site_of_record_id == 10
    assert call_args.michelin_level == "2"
    assert call_args.status == JobStatus.RUNNING
