"""Text extractor - extract structured text from wine list PDFs and HTML."""
from pathlib import Path
from typing import Optional

import pdfplumber
from bs4 import BeautifulSoup


class WineListTextExtractor:
    """Extract structured text from wine list files."""
    
    def extract_from_file(self, file_path: str) -> str:
        """
        Extract text from wine list file (PDF or HTML).
        
        Args:
            file_path: Path to wine list file
        
        Returns:
            Extracted text with structure preserved
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Determine file type and extract
        if path.suffix.lower() == '.pdf':
            return self._extract_from_pdf(path)
        elif path.suffix.lower() in ['.html', '.htm']:
            return self._extract_from_html(path)
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")
    
    def extract_and_save(self, file_path: str, output_path: Optional[str] = None) -> str:
        """
        Extract text and save to output file.
        
        Args:
            file_path: Path to wine list file
            output_path: Optional path for output text file. 
                        If not provided, uses same name with .txt extension
        
        Returns:
            Path to output text file
        """
        # Extract text
        text = self.extract_from_file(file_path)
        
        # Determine output path
        if output_path is None:
            path = Path(file_path)
            output_path = str(path.with_suffix('.txt'))
        
        # Save text
        Path(output_path).write_text(text, encoding='utf-8')
        
        return output_path
    
    def _extract_from_pdf(self, path: Path) -> str:
        """
        Extract text from PDF while preserving layout.
        
        Args:
            path: Path to PDF file
        
        Returns:
            Extracted text with layout preserved
        """
        extracted_text = []
        
        try:
            with pdfplumber.open(path) as pdf:
                total_pages = len(pdf.pages)
                
                for page_num, page in enumerate(pdf.pages, start=1):
                    # Add page separator
                    extracted_text.append(f"\n{'='*80}\n")
                    extracted_text.append(f"PAGE {page_num} of {total_pages}\n")
                    extracted_text.append(f"{'='*80}\n\n")
                    
                    # Try to extract tables first
                    tables = page.extract_tables()
                    
                    if tables:
                        # Page has tables - extract and format them
                        for table_num, table in enumerate(tables, start=1):
                            extracted_text.append(f"[TABLE {table_num}]\n")
                            extracted_text.append(self._format_table(table))
                            extracted_text.append("\n")
                    
                    # Extract text with layout preservation
                    # layout=True maintains horizontal positioning
                    text = page.extract_text(layout=True)
                    
                    if text:
                        # Only add text if tables weren't found or as supplement
                        if not tables:
                            extracted_text.append(text)
                        else:
                            # Add non-table text as well (may include headers, footers, etc.)
                            extracted_text.append("\n[TEXT CONTENT]\n")
                            extracted_text.append(text)
                    
                    extracted_text.append("\n")
        
        except Exception as e:
            raise Exception(f"Error extracting text from PDF: {e}")
        
        return "".join(extracted_text)
    
    def _format_table(self, table: list) -> str:
        """
        Format extracted table as structured text.
        
        Args:
            table: List of rows (each row is a list of cells)
        
        Returns:
            Formatted table as text
        """
        if not table:
            return ""
        
        formatted_rows = []
        
        # Determine column widths
        col_widths = []
        for row in table:
            for i, cell in enumerate(row):
                cell_str = str(cell) if cell is not None else ""
                if i >= len(col_widths):
                    col_widths.append(len(cell_str))
                else:
                    col_widths[i] = max(col_widths[i], len(cell_str))
        
        # Format each row
        for row_num, row in enumerate(table):
            cells = []
            for i, cell in enumerate(row):
                cell_str = str(cell) if cell is not None else ""
                # Pad to column width
                if i < len(col_widths):
                    cells.append(cell_str.ljust(col_widths[i]))
                else:
                    cells.append(cell_str)
            
            # Join cells with separator
            formatted_row = " | ".join(cells)
            formatted_rows.append(formatted_row)
            
            # Add separator line after header (first row)
            if row_num == 0:
                separator = "-" * len(formatted_row)
                formatted_rows.append(separator)
        
        return "\n".join(formatted_rows)
    
    def _extract_from_html(self, path: Path) -> str:
        """
        Extract text from HTML while preserving structure.

        Uses a two-pass strategy:
          1. Semantic extraction – looks for standard HTML tags (h1-h6, p, ul,
             ol, table) which works well for traditional server-rendered pages.
          2. Full-text fallback – if semantic extraction yields very little
             content (common with JS-rendered SPA pages like Binwise that use
             divs/spans instead of semantic tags), falls back to extracting
             all visible text with basic block-level separation.

        Args:
            path: Path to HTML file

        Returns:
            Extracted text with structure preserved
        """
        try:
            html_content = path.read_text(encoding='utf-8')
            soup = BeautifulSoup(html_content, 'html.parser')

            # Remove script, style, and noscript elements
            for tag in soup(["script", "style", "noscript", "svg", "meta", "link"]):
                tag.decompose()

            # Run both extraction strategies and pick the richer result.
            # Semantic extraction works best for traditional server-rendered
            # HTML.  Full-text extraction wins for SPA-rendered pages (React,
            # Vue, etc.) where content lives in divs/spans, not semantic tags.
            semantic_text = self._semantic_extract(soup)
            fulltext_text = self._fulltext_extract(soup)

            semantic_len = len(semantic_text.strip())
            fulltext_len = len(fulltext_text.strip())

            # Use fulltext if it has significantly more content (>2x) or if
            # semantic extraction captured very little.
            if fulltext_len > semantic_len * 2 or semantic_len < 200:
                return fulltext_text

            return semantic_text

        except Exception as e:
            raise Exception(f"Error extracting text from HTML: {e}")

    def _semantic_extract(self, soup: BeautifulSoup) -> str:
        """Extract text using semantic HTML tags (h1-h6, p, ul, ol, table)."""
        extracted_text = []

        for element in soup.find_all(
            ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'table']
        ):
            if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(element.name[1])
                prefix = '#' * level
                text = element.get_text(strip=True)
                if text:
                    extracted_text.append(f"\n{prefix} {text}\n")

            elif element.name == 'p':
                text = element.get_text(strip=True)
                if text:
                    extracted_text.append(f"{text}\n")

            elif element.name in ['ul', 'ol']:
                for li in element.find_all('li', recursive=False):
                    text = li.get_text(strip=True)
                    if text:
                        extracted_text.append(f"  • {text}\n")

            elif element.name == 'table':
                extracted_text.append("\n[TABLE]\n")
                for row in element.find_all('tr'):
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        row_text = " | ".join(
                            cell.get_text(strip=True) for cell in cells
                        )
                        extracted_text.append(f"{row_text}\n")
                extracted_text.append("\n")

        return "".join(extracted_text)

    def _fulltext_extract(self, soup: BeautifulSoup) -> str:
        """Extract all visible text with block-level separation.

        Works well for SPA-rendered pages (React, Vue, Angular) that use
        divs and spans instead of semantic HTML.  Inserts newlines at
        block-level boundaries to preserve visual structure.
        """
        _BLOCK_TAGS = frozenset([
            'div', 'section', 'article', 'aside', 'header', 'footer',
            'nav', 'main', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'p', 'blockquote', 'pre', 'ul', 'ol', 'li', 'table',
            'tr', 'td', 'th', 'br', 'hr', 'dd', 'dt', 'dl',
            'figcaption', 'figure', 'details', 'summary',
        ])

        lines: list[str] = []
        current_line: list[str] = []

        def _flush():
            text = ' '.join(current_line).strip()
            if text:
                lines.append(text)
            current_line.clear()

        def _walk(node):
            if isinstance(node, str):
                # NavigableString
                text = node.strip()
                if text:
                    current_line.append(text)
                return

            if not hasattr(node, 'name'):
                return

            tag_name = (node.name or '').lower()

            # Skip hidden elements
            style = node.get('style', '')
            if 'display:none' in style.replace(' ', '') or \
               'visibility:hidden' in style.replace(' ', ''):
                return

            is_block = tag_name in _BLOCK_TAGS

            if is_block:
                _flush()

            for child in node.children:
                _walk(child)

            if is_block:
                _flush()

        body = soup.find('body') or soup
        _walk(body)
        _flush()

        # Collapse multiple blank lines
        output: list[str] = []
        prev_blank = False
        for line in lines:
            if not line:
                if not prev_blank:
                    output.append('')
                prev_blank = True
            else:
                output.append(line)
                prev_blank = False

        return '\n'.join(output)
