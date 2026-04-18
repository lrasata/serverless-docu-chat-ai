export const APP_NAME = "AI Powered Chatbot";
export const API_BACKEND_URL = import.meta.env.VITE_API_GW_BACKEND_ENDPOINT;

export const AWS_COGNITO_USER_POOL_API_ENDPOINT = import.meta.env
  .VITE_AWS_COGNITO_USER_POOL_API_ENDPOINT;
export const AWS_HOSTED_COGNITO_LOGIN_DOMAIN = import.meta.env
  .VITE_AWS_HOSTED_COGNITO_LOGIN_DOMAIN;
export const AWS_COGNITO_CLIENT_ID = import.meta.env.VITE_AWS_COGNITO_CLIENT_ID;
export const AWS_COGNITO_REDIRECT_URI = import.meta.env
  .VITE_AWS_COGNITO_REDIRECT_URI;
export const AWS_COGNITO_RESPONSE = "code";
export const AWS_COGNITO_SCOPE = "openid email profile";
