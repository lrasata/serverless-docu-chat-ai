import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import type { AuthContextProps } from "react-oidc-context";
import React from "react";
import Typography from "@mui/material/Typography";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import QuestionAnswerIcon from "@mui/icons-material/QuestionAnswer";

interface SignInWithGoogleProps {
  googleImgSrc: string;
  googleImgAlt: string;
  buttonText: string;
  auth: AuthContextProps;
}
const SignInWithGoogle: React.FC<SignInWithGoogleProps> = ({
  googleImgAlt,
  googleImgSrc,
  buttonText,
  auth,
}) => (
  <Box
    display="flex"
    flexDirection="column"
    justifyContent="center"
    alignItems="center"
    height="100vh"
  >
    <QuestionAnswerIcon sx={{ fontSize: 60, my: 2 }} color="primary" />
    <Typography variant="h2" mb={3}>
      AI Powered Chatbot
    </Typography>
    <Card
      sx={{
        minWidth: 500,
        minHeight: 150,
        backgroundColor: "grey.100",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
      }}
    >
      <CardContent>
        <Typography variant="body1" mb={2}>
          Chat with your documents and more using AI.
        </Typography>
        <Button
          onClick={() => auth.signinRedirect()}
          variant="outlined"
          startIcon={
            <img src={googleImgSrc} alt={googleImgAlt} width="16" height="16" />
          }
        >
          {buttonText}
        </Button>
      </CardContent>
    </Card>
  </Box>
);

export default SignInWithGoogle;
