import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import { AuthProvider } from "react-oidc-context";
import store from "./app/shared/store/redux";
import {
  AWS_COGNITO_CLIENT_ID,
  AWS_COGNITO_USER_POOL_API_ENDPOINT,
  AWS_COGNITO_REDIRECT_URI,
  AWS_COGNITO_RESPONSE,
  AWS_COGNITO_SCOPE,
  AWS_HOSTED_COGNITO_LOGIN_DOMAIN,
} from "./app/shared/constants/constants.ts";
import { Provider } from "react-redux";

const cognitoAuthConfig = {
  authority: AWS_COGNITO_USER_POOL_API_ENDPOINT,
  client_id: AWS_COGNITO_CLIENT_ID,
  redirect_uri: AWS_COGNITO_REDIRECT_URI,
  post_logout_redirect_uri: AWS_COGNITO_REDIRECT_URI,
  response_type: AWS_COGNITO_RESPONSE,
  scope: AWS_COGNITO_SCOPE,
  metadata: {
    issuer: AWS_HOSTED_COGNITO_LOGIN_DOMAIN,
    authorization_endpoint: `${AWS_HOSTED_COGNITO_LOGIN_DOMAIN}/oauth2/authorize`,
    token_endpoint: `${AWS_HOSTED_COGNITO_LOGIN_DOMAIN}/oauth2/token`,
    userinfo_endpoint: `${AWS_HOSTED_COGNITO_LOGIN_DOMAIN}/oauth2/userInfo`,
    end_session_endpoint: `${AWS_HOSTED_COGNITO_LOGIN_DOMAIN}/logout`,
  },
};

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider
      {...cognitoAuthConfig}
      onSigninCallback={() => {
        // Remove the one-time OAuth code and state from the URL so a page
        // refresh does not try to redeem an already-consumed code.
        window.history.replaceState({}, document.title, window.location.pathname);
      }}
    >
      <Provider store={store}>
        <App />
      </Provider>
    </AuthProvider>
  </StrictMode>,
);
