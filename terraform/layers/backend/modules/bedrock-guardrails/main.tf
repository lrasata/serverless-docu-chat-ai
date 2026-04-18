resource "aws_bedrock_guardrail" "main" {
  name                      = "${var.environment}-${var.app_id}-bedrock-guardrail"
  description               = "Filters violence, sexual content, hate speech, insults, profanity and redacts PII from inputs and outputs"
  blocked_input_messaging   = "Your message was blocked due to content policy violations."
  blocked_outputs_messaging = "The response was blocked due to content policy violations."

  content_policy_config {
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }

  # sensitive_information_policy_config {
  #   pii_entities_config {
  #     type          = "NAME"
  #     action        = "ANONYMIZE"
  #     input_action  = "ANONYMIZE"
  #     output_action = "ANONYMIZE"
  #   }
  #   pii_entities_config {
  #     type          = "EMAIL"
  #     action        = "ANONYMIZE"
  #     input_action  = "ANONYMIZE"
  #     output_action = "ANONYMIZE"
  #   }
  #   pii_entities_config {
  #     type          = "PHONE"
  #     action        = "ANONYMIZE"
  #     input_action  = "ANONYMIZE"
  #     output_action = "ANONYMIZE"
  #   }
  # }

  word_policy_config {
    managed_word_lists_config {
      type = "PROFANITY"
    }
  }

  tags = {
    Environment = var.environment
    App         = var.app_id
  }
}

resource "aws_bedrock_guardrail_version" "main" {
  guardrail_arn = aws_bedrock_guardrail.main.guardrail_arn
  description   = "Initial version"
}
