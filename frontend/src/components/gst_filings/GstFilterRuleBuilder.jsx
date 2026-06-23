import React from 'react';
import { Plus, X } from 'lucide-react';
import FormCustomSelect from '../common/FormCustomSelect';
import FilterDateInput from '../common/FilterDateInput';
import { optionsFromPairs } from '../common/selectOptionUtils';

const GstFilterRuleBuilder = ({
  title,
  hint,
  matchMode,
  onMatchModeChange,
  rules = [],
  onRulesChange,
  createEmptyRule,
  columns = [],
  minRules = 1,
  className = '',
}) => {
  const updateRule = (index, key, value) => {
    const next = [...rules];
    next[index] = { ...next[index], [key]: value };
    onRulesChange(next);
  };

  const removeRule = (index) => {
    const next = rules.filter((_, i) => i !== index);
    onRulesChange(next.length ? next : [createEmptyRule()]);
  };

  const addRule = () => {
    onRulesChange([...(rules || []), createEmptyRule()]);
  };

  const renderColumn = (column, rule, index) => {
    if (column.type === 'date') {
      return (
        <div key={`${column.key}-${index}`} className="gst-filter-rule-date-cell">
          {column.label && <span className="gst-filter-rule-date-label">{column.label}</span>}
          <FilterDateInput
            value={rule[column.key] || ''}
            onChange={(e) => updateRule(index, column.key, e.target.value)}
            ariaLabel={column.ariaLabel || column.label || column.key}
          />
        </div>
      );
    }

    const options = column.getOptions
      ? column.getOptions(rule, index)
      : (column.options || []);

    return (
      <FormCustomSelect
        key={`${column.key}-${index}`}
        name={`${column.key}_${index}`}
        value={rule[column.key] || ''}
        onChange={(e) => {
          const nextValue = e.target.value;
          const nextRule = { ...rule, [column.key]: nextValue };
          if (column.clearOnChange) {
            column.clearOnChange.forEach((field) => {
              nextRule[field] = '';
            });
          }
          const next = [...rules];
          next[index] = nextRule;
          onRulesChange(next);
        }}
        options={optionsFromPairs([
          { value: '', label: column.placeholder || 'Select' },
          ...options,
        ])}
        placeholder={column.placeholder || 'Select'}
        ariaLabel={column.ariaLabel || column.label || column.key}
      />
    );
  };

  return (
    <div className={`filter-group-v4 gst-return-status-rules-panel ${className}`.trim()}>
      <div className="gst-return-status-rules-header">
        <label>{title}</label>
        <div className="gst-return-status-match-toggle">
          <button
            type="button"
            className={matchMode === 'AND' ? 'active' : ''}
            onClick={() => onMatchModeChange('AND')}
          >
            AND
          </button>
          <button
            type="button"
            className={matchMode === 'OR' ? 'active' : ''}
            onClick={() => onMatchModeChange('OR')}
          >
            OR
          </button>
        </div>
      </div>
      {hint && <p className="gst-return-status-rules-hint">{hint}</p>}
      {(rules || []).map((rule, index) => (
        <div key={`filter-rule-${index}`} className="gst-return-status-rule-row">
          {columns.map((column) => renderColumn(column, rule, index))}
          <button
            type="button"
            className="gst-return-status-rule-remove"
            title="Remove rule"
            disabled={(rules || []).length <= minRules}
            onClick={() => removeRule(index)}
          >
            <X size={14} />
          </button>
        </div>
      ))}
      <button type="button" className="gst-return-status-rule-add" onClick={addRule}>
        <Plus size={14} />
        Add rule
      </button>
    </div>
  );
};

export default GstFilterRuleBuilder;
