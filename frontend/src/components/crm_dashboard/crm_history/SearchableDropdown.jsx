import React, { useState, useRef, useEffect } from 'react';
import { Search, X, Check, ChevronDown } from 'lucide-react';

const SearchableDropdown = ({ 
  options = [], 
  selected = [], 
  onChange, 
  placeholder = "Select options...", 
  label,
  isSingle = false,
  allowCustom = false,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const dropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const filteredOptions = options.filter(opt => 
    (opt.label || opt.name || opt.toString()).toLowerCase().includes(searchTerm.toLowerCase())
  );

  const trimmedSearch = searchTerm.trim();
  const canAddCustom = allowCustom
    && trimmedSearch
    && !options.some((opt) => String(opt.value ?? opt.label ?? '').toLowerCase() === trimmedSearch.toLowerCase())
    && !(isSingle ? selected === trimmedSearch : selected.includes(trimmedSearch));

  const addCustomValue = (value) => {
    const val = String(value).trim();
    if (!val) return;
    if (isSingle) {
      onChange(val);
      setIsOpen(false);
    } else if (!selected.includes(val)) {
      onChange([...selected, val]);
    }
    setSearchTerm('');
  };

  const handleSearchKeyDown = (e) => {
    if (e.key === 'Enter' && canAddCustom) {
      e.preventDefault();
      e.stopPropagation();
      addCustomValue(trimmedSearch);
    }
  };

  const handleToggle = (value) => {
    if (isSingle) {
      onChange(value);
      setIsOpen(false);
      return;
    }

    const updated = selected.includes(value)
      ? selected.filter(v => v !== value)
      : [...selected, value];
    onChange(updated);
  };

  const removeSelected = (e, value) => {
    e.stopPropagation();
    onChange(selected.filter(v => v !== value));
  };

  return (
    <div className="searchable-dropdown-container" ref={dropdownRef}>
      {label && <label className="dropdown-label">{label}</label>}
      
      <div 
        className={`dropdown-box ${isOpen ? 'open' : ''}`} 
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="selected-items-area">
          {selected.length === 0 ? (
            <span className="placeholder">{placeholder}</span>
          ) : isSingle ? (
            <span className="single-val">
              {options.find(o => o.value === selected)?.label || selected}
            </span>
          ) : (
            <div className="selected-chips">
              {selected.map(val => {
                const opt = options.find(o => o.value === val);
                return (
                  <span key={val} className="dropdown-chip">
                    {opt ? opt.label : val}
                    <X size={12} onClick={(e) => removeSelected(e, val)} />
                  </span>
                );
              })}
            </div>
          )}
        </div>
        <ChevronDown size={16} className={`chevron ${isOpen ? 'up' : ''}`} />
      </div>

      {isOpen && (
        <div className="dropdown-menu">
          <div className="dropdown-search">
            <Search size={14} />
            <input 
              type="text" 
              placeholder={allowCustom ? 'Search or type to add...' : 'Search...'}
              autoFocus
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          <div className="dropdown-options scrollable">
            {canAddCustom && (
              <div
                className="dropdown-option add-custom"
                onClick={(e) => {
                  e.stopPropagation();
                  addCustomValue(trimmedSearch);
                }}
              >
                <span>Add &ldquo;{trimmedSearch}&rdquo;</span>
              </div>
            )}
            {filteredOptions.length === 0 && !canAddCustom ? (
              <div className="no-options">No matches found</div>
            ) : (
              filteredOptions.map(opt => {
                const isSelected = isSingle ? selected === opt.value : selected.includes(opt.value);
                return (
                  <div 
                    key={opt.value} 
                    className={`dropdown-option ${isSelected ? 'selected' : ''}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleToggle(opt.value);
                    }}
                  >
                    <div className="option-check">
                      {isSelected && <Check size={14} />}
                    </div>
                    <span>{opt.label || opt.name}</span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default SearchableDropdown;
