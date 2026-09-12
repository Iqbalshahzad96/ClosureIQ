import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import Header from '../Header';

describe('Header', () => {
  it('displays Period: Not selected without hardcoded 2026-Q1', () => {
    render(<Header healthStatus={{ status: 'healthy' }} />);

    expect(screen.getByText('Period: Not selected')).toBeInTheDocument();
    expect(screen.queryByText(/2026-Q1/i)).not.toBeInTheDocument();
  });
});

