import React, { useMemo, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';

type Message = {
  id: string;
  text: string;
  model: string;
};

const initialMessages: Message[] = [
  {
    id: 'intro',
    text: 'Select a model in the input bar before sending a message.',
    model: 'system',
  },
];

export default function ModelSelectorScreen() {
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [draft, setDraft] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState('gpt5.2');

  const modelOptions = useMemo(() => ['gpt5.2', 'gpt-4o-mini', 'gpt-4.1'], []);

  const canSend = draft.trim().length > 0;

  const handleSend = () => {
    const trimmed = draft.trim();
    if (!trimmed) {
      return;
    }

    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${selectedModel}`,
        text: trimmed,
        model: selectedModel,
      },
    ]);
    setDraft('');
  };

  const handleModelSelect = (model: string) => {
    setSelectedModel(model);
    setMenuOpen(false);
  };

  return (
    <ThemedView style={styles.container}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.select({ ios: 'padding', android: undefined })}
      >
        <ScrollView contentContainerStyle={styles.messages} keyboardShouldPersistTaps="handled">
          <ThemedText type="title">Model Selector Input</ThemedText>
          <ThemedText style={styles.subtitle}>
            The input bar includes a model selector so you can choose gpt5.2 before sending.
          </ThemedText>
          {messages.map((message) => (
            <View key={message.id} style={styles.messageBubble}>
              <ThemedText style={styles.messageModel}>{message.model}</ThemedText>
              <ThemedText>{message.text}</ThemedText>
            </View>
          ))}
        </ScrollView>
        <View style={styles.inputRow}>
          <View style={styles.modelSelector}>
            <Pressable onPress={() => setMenuOpen((prev) => !prev)} style={styles.modelButton}>
              <ThemedText style={styles.modelButtonText}>{selectedModel}</ThemedText>
            </Pressable>
            {menuOpen && (
              <View style={styles.modelMenu}>
                {modelOptions.map((model) => (
                  <Pressable
                    key={model}
                    onPress={() => handleModelSelect(model)}
                    style={styles.modelMenuItem}
                  >
                    <ThemedText
                      style={[
                        styles.modelMenuText,
                        model === selectedModel && styles.modelMenuTextActive,
                      ]}
                    >
                      {model}
                    </ThemedText>
                  </Pressable>
                ))}
              </View>
            )}
          </View>
          <TextInput
            style={styles.input}
            placeholder="Type your prompt"
            placeholderTextColor="rgba(0,0,0,0.4)"
            value={draft}
            onChangeText={setDraft}
            onSubmitEditing={handleSend}
            returnKeyType="send"
          />
          <Pressable
            style={[styles.sendButton, !canSend && styles.sendButtonDisabled]}
            disabled={!canSend}
            onPress={handleSend}
          >
            <ThemedText style={styles.sendButtonText}>Send</ThemedText>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  flex: {
    flex: 1,
  },
  messages: {
    padding: 20,
    gap: 16,
  },
  subtitle: {
    opacity: 0.7,
  },
  messageBubble: {
    borderRadius: 16,
    padding: 12,
    gap: 6,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.08)',
    backgroundColor: 'rgba(0,0,0,0.02)',
  },
  messageModel: {
    fontSize: 12,
    opacity: 0.6,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: 16,
    borderTopWidth: 1,
    borderColor: 'rgba(0,0,0,0.08)',
  },
  modelSelector: {
    position: 'relative',
  },
  modelButton: {
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.2)',
    backgroundColor: 'rgba(0,0,0,0.04)',
  },
  modelButtonText: {
    fontSize: 12,
  },
  modelMenu: {
    position: 'absolute',
    bottom: 48,
    left: 0,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.12)',
    backgroundColor: '#fff',
    paddingVertical: 6,
    minWidth: 140,
    shadowColor: '#000',
    shadowOpacity: 0.12,
    shadowRadius: 10,
    elevation: 4,
  },
  modelMenuItem: {
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  modelMenuText: {
    fontSize: 12,
  },
  modelMenuTextActive: {
    opacity: 0.8,
    fontWeight: '600',
  },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.2)',
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  sendButton: {
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 16,
    backgroundColor: '#2563EB',
  },
  sendButtonDisabled: {
    opacity: 0.5,
  },
  sendButtonText: {
    color: '#fff',
  },
});
