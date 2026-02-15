"""Test PDF text extraction."""
import pytest
from pathlib import Path

from winerank.crawler.text_extractor import WineListTextExtractor


@pytest.fixture
def extractor():
    """Create a text extractor instance."""
    return WineListTextExtractor()


@pytest.fixture
def example_pdfs():
    """Get list of example PDF files."""
    examples_dir = Path("data/examples")
    if examples_dir.exists():
        return list(examples_dir.glob("*.pdf"))
    return []


def test_extractor_initialization(extractor):
    """Test that extractor can be initialized."""
    assert extractor is not None


def test_extract_from_example_pdfs(extractor, example_pdfs):
    """Test extraction on example PDF files."""
    if not example_pdfs:
        pytest.skip("No example PDFs found")
    
    successful_extractions = 0
    
    for pdf_path in example_pdfs[:5]:  # Test first 5 PDFs
        try:
            # Extract text
            text = extractor.extract_from_file(str(pdf_path))
            
            # Verify we got some text
            assert text is not None
            assert len(text) > 0
            
            # Should contain common wine list keywords
            text_lower = text.lower()
            wine_indicators = ['wine', 'bottle', 'glass', 'red', 'white']
            has_indicator = any(indicator in text_lower for indicator in wine_indicators)
            assert has_indicator, f"No wine indicators found in {pdf_path.name}"
            
            successful_extractions += 1
        except Exception as e:
            # Skip corrupted PDFs
            print(f"Skipping {pdf_path.name}: {e}")
            continue
    
    # At least one PDF should extract successfully
    assert successful_extractions > 0, "No PDFs extracted successfully"


def test_extract_and_save(extractor, example_pdfs, tmp_path):
    """Test extract and save functionality."""
    if not example_pdfs:
        pytest.skip("No example PDFs found")
    
    # Try multiple PDFs until we find a valid one
    for pdf_path in example_pdfs[:5]:
        try:
            output_path = tmp_path / f"extracted_{pdf_path.stem}.txt"
            
            # Extract and save
            result_path = extractor.extract_and_save(str(pdf_path), str(output_path))
            
            # Verify file was created
            assert Path(result_path).exists()
            content = Path(result_path).read_text(encoding='utf-8')
            assert content
            
            # Success - return after first valid PDF
            return
        except Exception as e:
            # Try next PDF
            print(f"Skipping {pdf_path.name}: {e}")
            continue
    
    # If we get here, no PDFs worked
    pytest.fail("No valid PDFs found for extraction")


def test_extract_nonexistent_file(extractor):
    """Test extraction with nonexistent file."""
    with pytest.raises(FileNotFoundError):
        extractor.extract_from_file("/path/to/nonexistent.pdf")


def test_extract_unsupported_format(extractor, tmp_path):
    """Test extraction with unsupported file format."""
    # Create a dummy file with wrong extension
    dummy_file = tmp_path / "test.txt"
    dummy_file.write_text("Not a PDF")
    
    with pytest.raises(ValueError):
        extractor.extract_from_file(str(dummy_file))
