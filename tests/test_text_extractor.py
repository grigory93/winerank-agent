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


def test_extract_semantic_html(extractor, tmp_path):
    """Test extraction from standard server-rendered HTML with semantic tags."""
    html_file = tmp_path / "wine_list.html"
    html_file.write_text("""<!doctype html>
<html><body>
<h1>Wine List</h1>
<h2>Red Wines</h2>
<p>Chateau Margaux 2015 - $350</p>
<p>Opus One 2018 - $500</p>
<h2>White Wines</h2>
<p>Puligny-Montrachet 2019 - $180</p>
<table><tr><th>Wine</th><th>Price</th></tr>
<tr><td>Chablis Grand Cru</td><td>$120</td></tr></table>
</body></html>""", encoding='utf-8')

    text = extractor.extract_from_file(str(html_file))
    assert "Wine List" in text
    assert "Red Wines" in text
    assert "Chateau Margaux" in text
    assert "Opus One" in text
    assert "Puligny-Montrachet" in text
    assert "Chablis Grand Cru" in text


def test_extract_spa_rendered_html(extractor, tmp_path):
    """Test extraction from SPA-rendered HTML using divs/spans (like Binwise).

    When semantic extraction yields little content, the extractor should
    fall back to full-text extraction from divs and spans.
    """
    html_file = tmp_path / "wine_list.html"
    html_file.write_text("""<!doctype html>
<html><body>
<div id="root">
  <div class="header"><div>Per Se</div><div>Wine List</div></div>
  <div class="section">
    <div class="category">BY THE GLASS</div>
    <div class="item">
      <span class="name">Krug, Grande Cuvée, NV</span>
      <span class="price">$85</span>
    </div>
    <div class="item">
      <span class="name">Dom Pérignon, 2012</span>
      <span class="price">$120</span>
    </div>
  </div>
  <div class="section">
    <div class="category">CHAMPAGNE</div>
    <div class="item">
      <span class="name">Louis Roederer, Cristal, 2014</span>
      <span class="price">$650</span>
    </div>
  </div>
</div>
</body></html>""", encoding='utf-8')

    text = extractor.extract_from_file(str(html_file))
    assert "Per Se" in text
    assert "Wine List" in text
    assert "BY THE GLASS" in text
    assert "Krug" in text
    assert "Dom Pérignon" in text
    assert "CHAMPAGNE" in text
    assert "Louis Roederer" in text


def test_spa_shell_detection():
    """Test that the downloader correctly identifies SPA shell pages."""
    from winerank.crawler.downloader import WineListDownloader

    downloader = WineListDownloader()

    # Typical React SPA shell (like the Binwise Per Se page)
    spa_html = """<!doctype html><html lang="en"><head>
    <title>Binwise: Digital Food and Beverage Menu</title>
    <link href="./static/css/main.67e6cee6.chunk.css" rel="stylesheet">
    </head><body>
    <noscript>You need to enable JavaScript to run this app.</noscript>
    <div id="root"></div>
    <script>!function(e){var t=e.webpackJsonpbw_winelist}([])</script>
    <script src="./static/js/main.efe789d7.chunk.js"></script>
    </body></html>"""
    assert downloader._is_spa_shell(spa_html) is True

    # Regular server-rendered HTML with real content
    regular_html = """<!doctype html><html><body>
    <h1>Restaurant Wine List</h1>
    <h2>Red Wines</h2>
    <p>Chateau Margaux 2015 - $350</p>
    <p>Opus One 2018 Napa Valley Cabernet Sauvignon - $500</p>
    <p>Screaming Eagle 2019 - $3,200</p>
    </body></html>"""
    assert downloader._is_spa_shell(regular_html) is False
