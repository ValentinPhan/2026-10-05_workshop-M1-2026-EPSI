import React, { useCallback, useEffect, useState } from 'react';
import { App as AntApp, Button, Flex, Form, Input, List, Modal, Popconfirm, Select, Space, Table, Typography } from 'antd';
import { deleteJson, getJson, postJson } from '../api.js';
import { Panel, StatusTag } from './ui.jsx';

// Réservé aux administrateurs : création / suppression de comptes, réinitialisation de mot de passe,
// et dernières actions sensibles (journal d'audit).
const ROLE_LABEL = { admin: 'administrateur', agent: 'agent' };
const ACTION_LABEL = {
  login: 'connexion', login_failed: 'échec de connexion', logout: 'déconnexion', motor: 'moteur / caméra',
  vision_source: 'source vidéo', scenario: 'simulation', user_create: 'compte créé', user_delete: 'compte supprimé',
  password_reset: 'mot de passe réinitialisé', bootstrap: 'premier admin créé',
};

export default function UsersPanel({ currentUser }) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm();
  const [users, setUsers] = useState([]);
  const [audit, setAudit] = useState([]);
  const [resetFor, setResetFor] = useState(null); // utilisateur dont on change le mot de passe
  const [newPassword, setNewPassword] = useState('');

  const refresh = useCallback(
    () =>
      Promise.all([getJson('/api/users'), getJson('/api/audit?limit=15')])
        .then(([u, a]) => {
          setUsers(u);
          setAudit(a);
        })
        .catch((e) => message.error(e.message)),
    [message],
  );
  useEffect(() => {
    refresh();
  }, [refresh]);

  const run = async (action, success) => {
    try {
      await action();
      message.success(success);
      refresh();
      return true;
    } catch (e) {
      message.error(e.message);
      return false;
    }
  };

  const create = (values) => run(() => postJson('/api/users', values), `Compte « ${values.username} » créé`).then((ok) => ok && form.resetFields());
  const remove = (user) => run(() => deleteJson(`/api/users/${user.id}`), `Compte « ${user.username} » supprimé`);
  const resetPassword = async () => {
    if (await run(() => postJson(`/api/users/${resetFor.id}/password`, { password: newPassword }), 'Mot de passe modifié')) {
      setResetFor(null);
      setNewPassword('');
    }
  };

  return (
    <Panel title="Comptes et journal d'audit" extra={<StatusTag tone="info">administrateur</StatusTag>}>
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={users}
        columns={[
          { title: 'Identifiant', dataIndex: 'username' },
          { title: 'Rôle', dataIndex: 'role', render: (r) => <StatusTag tone={r === 'admin' ? 'info' : 'neutral'}>{ROLE_LABEL[r]}</StatusTag> },
          {
            title: '',
            align: 'right',
            render: (_, u) => (
              <Space size="small">
                <Button size="small" onClick={() => setResetFor(u)}>Mot de passe</Button>
                <Popconfirm title={`Supprimer « ${u.username} » ?`} okText="Supprimer" cancelText="Annuler" onConfirm={() => remove(u)} disabled={u.username === currentUser.username}>
                  <Button size="small" danger disabled={u.username === currentUser.username}>Supprimer</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Form form={form} layout="inline" onFinish={create} initialValues={{ role: 'agent' }} style={{ rowGap: 8 }}>
        <Form.Item name="username" rules={[{ required: true, message: '' }]}>
          <Input placeholder="Identifiant" autoComplete="off" style={{ width: 130 }} />
        </Form.Item>
        <Form.Item name="password" rules={[{ required: true, message: '' }]}>
          <Input.Password placeholder="Mot de passe (8+)" autoComplete="new-password" style={{ width: 160 }} />
        </Form.Item>
        <Form.Item name="role">
          <Select style={{ width: 130 }} options={[{ value: 'agent', label: 'Agent' }, { value: 'admin', label: 'Administrateur' }]} />
        </Form.Item>
        <Button type="primary" htmlType="submit">Créer</Button>
      </Form>

      <Typography.Text type="secondary">Dernières actions</Typography.Text>
      <List
        size="small"
        style={{ maxHeight: 200, overflowY: 'auto' }}
        dataSource={audit}
        rowKey="id"
        renderItem={(a) => (
          <List.Item>
            <Flex gap={10} wrap style={{ fontSize: 12 }}>
              <Typography.Text type="secondary">{new Date(a.ts).toLocaleTimeString('fr-FR')}</Typography.Text>
              <strong>{a.username ?? 'système'}</strong>
              <span>{ACTION_LABEL[a.action] ?? a.action}</span>
              <Typography.Text type="secondary" ellipsis style={{ maxWidth: 180 }}>{a.detail}</Typography.Text>
            </Flex>
          </List.Item>
        )}
      />

      <Modal
        open={Boolean(resetFor)}
        title={`Nouveau mot de passe — ${resetFor?.username ?? ''}`}
        okText="Modifier"
        cancelText="Annuler"
        onOk={resetPassword}
        onCancel={() => setResetFor(null)}
        okButtonProps={{ disabled: newPassword.length < 8 }}
        destroyOnHidden
      >
        <Input.Password value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="8 caractères minimum" autoComplete="new-password" />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>Ses sessions ouvertes seront fermées.</Typography.Text>
      </Modal>
    </Panel>
  );
}
