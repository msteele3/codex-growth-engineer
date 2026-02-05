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
  sender: 'user' | 'avatar';
  text: string;
};

const initialMessages: Message[] = [
  {
    id: 'intro',
    sender: 'avatar',
    text: "Hi! I'm your AI avatar. Ask me anything and I'll respond with a quick template reply.",
  },
];

export default function AiAvatarChatScreen() {
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [draft, setDraft] = useState('');

  const canSend = draft.trim().length > 0;

  const quickReplies = useMemo(
    () => [
      'Tell me about the app status.',
      'What can you help me with?',
      'Share the next steps.',
    ],
    [],
  );

  const handleSend = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }

    const userMessage: Message = {
      id: `${Date.now()}-user`,
      sender: 'user',
      text: trimmed,
    };

    const avatarMessage: Message = {
      id: `${Date.now()}-avatar`,
      sender: 'avatar',
      text: `Thanks for reaching out! I'm on it. Here's a template response: \"${trimmed}\" received, and I'm preparing a follow-up for you now.`,
    };

    setMessages((prev) => [...prev, userMessage, avatarMessage]);
    setDraft('');
  };

  return (
    <ThemedView style={styles.container}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.select({ ios: 'padding', android: undefined })}>
        <ScrollView contentContainerStyle={styles.messages}>
          <ThemedText type="title">AI Avatar Chat</ThemedText>
          <ThemedText style={styles.subtitle}>
            Send a message and the avatar responds with a friendly template reply.
          </ThemedText>
          {messages.map((message) => (
            <View
              key={message.id}
              style={[
                styles.messageRow,
                message.sender === 'user' ? styles.messageRowUser : styles.messageRowAvatar,
              ]}>
              {message.sender === 'avatar' && (
                <View style={styles.avatar}>
                  <ThemedText style={styles.avatarText}>AI</ThemedText>
                </View>
              )}
              <View
                style={[
                  styles.messageBubble,
                  message.sender === 'user'
                    ? styles.messageBubbleUser
                    : styles.messageBubbleAvatar,
                ]}>
                <ThemedText>{message.text}</ThemedText>
              </View>
            </View>
          ))}
          <View style={styles.quickReplies}>
            {quickReplies.map((reply) => (
              <Pressable key={reply} style={styles.replyChip} onPress={() => handleSend(reply)}>
                <ThemedText style={styles.replyText}>{reply}</ThemedText>
              </Pressable>
            ))}
          </View>
        </ScrollView>
        <View style={styles.inputRow}>
          <TextInput
            style={styles.input}
            placeholder="Type your message"
            placeholderTextColor="rgba(0,0,0,0.4)"
            value={draft}
            onChangeText={setDraft}
            onSubmitEditing={() => handleSend(draft)}
            returnKeyType="send"
          />
          <Pressable
            style={[styles.sendButton, !canSend && styles.sendButtonDisabled]}
            disabled={!canSend}
            onPress={() => handleSend(draft)}>
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
  messageRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  messageRowUser: {
    justifyContent: 'flex-end',
  },
  messageRowAvatar: {
    justifyContent: 'flex-start',
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#5C7CFA',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    color: '#fff',
  },
  messageBubble: {
    maxWidth: '78%',
    padding: 12,
    borderRadius: 16,
  },
  messageBubbleUser: {
    backgroundColor: '#DDF2FF',
  },
  messageBubbleAvatar: {
    backgroundColor: '#F1F5F9',
  },
  quickReplies: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  replyChip: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.1)',
  },
  replyText: {
    fontSize: 12,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    padding: 16,
    borderTopWidth: 1,
    borderColor: 'rgba(0,0,0,0.08)',
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
    paddingHorizontal: 16,
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
