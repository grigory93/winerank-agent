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
        
        Args:
            path: Path to HTML file
        
        Returns:
            Extracted text with structure preserved
        """
        try:
            html_content = path.read_text(encoding='utf-8')
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            extracted_text = []
            
            # Process headings, lists, and paragraphs with structure
            for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'table']):
                if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    # Heading
                    level = int(element.name[1])
                    prefix = '#' * level
                    extracted_text.append(f"\n{prefix} {element.get_text(strip=True)}\n")
                
                elif element.name == 'p':
                    # Paragraph
                    text = element.get_text(strip=True)
                    if text:
                        extracted_text.append(f"{text}\n")
                
                elif element.name in ['ul', 'ol']:
                    # List
                    for li in element.find_all('li', recursive=False):
                        text = li.get_text(strip=True)
                        if text:
                            extracted_text.append(f"  • {text}\n")
                
                elif element.name == 'table':
                    # Table
                    extracted_text.append("\n[TABLE]\n")
                    for row in element.find_all('tr'):
                        cells = row.find_all(['td', 'th'])
                        if cells:
                            row_text = " | ".join(cell.get_text(strip=True) for cell in cells)
                            extracted_text.append(f"{row_text}\n")
                    extracted_text.append("\n")
            
            return "".join(extracted_text)
        
        except Exception as e:
            raise Exception(f"Error extracting text from HTML: {e}")
