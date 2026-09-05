import { apiClient } from './api';

export const healthService = {
  async getHealthStatus() {
    return apiClient('/health');
  }
};
